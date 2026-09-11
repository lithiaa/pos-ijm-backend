import asyncio
import json
import logging
import queue
import re
import threading
import time
from collections import OrderedDict
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from typing import Any, Callable

from app.database import SessionLocal
from app.models.audit_log import AuditLog
from config import AUDIT_TRUSTED_PROXIES


AUDITED_METHODS = {
    "POST": "CREATE",
    "PUT": "UPDATE",
    "PATCH": "UPDATE",
    "DELETE": "DELETE",
}
MAX_CAPTURE_BYTES = 16_384
MAX_SUMMARY_BYTES = 8_192
AUDIT_QUEUE_SIZE = 256
ANONYMOUS_AUDIT_LIMIT = 20
ANONYMOUS_AUDIT_WINDOW_SECONDS = 60.0
ANONYMOUS_AUDIT_MAX_SOURCES = 1_024
REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"password|passphrase|token|key|secret|authorization|cookie|base64|photo|foto|image|file",
    re.IGNORECASE,
)
logger = logging.getLogger(__name__)
TrustedNetwork = IPv4Network | IPv6Network


def parse_trusted_proxy_networks(value: str) -> tuple[TrustedNetwork, ...]:
    """Parse a comma-separated set of proxy IPs/CIDRs, ignoring invalid entries."""
    networks = []
    for item in value.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            networks.append(ip_network(candidate, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid AUDIT_TRUSTED_PROXIES entry")
    return tuple(networks)


TRUSTED_PROXY_NETWORKS = parse_trusted_proxy_networks(AUDIT_TRUSTED_PROXIES)


def _parsed_ip(value: str):
    try:
        return ip_address(value.strip())
    except ValueError:
        return None


def _is_trusted_proxy(host: str, trusted_proxies: tuple[TrustedNetwork, ...]) -> bool:
    address = _parsed_ip(host)
    return bool(
        address
        and (
            address.is_loopback
            or any(address in network for network in trusted_proxies)
        )
    )


def client_ip(
    scope: dict[str, Any],
    headers: dict[str, str],
    trusted_proxies: tuple[TrustedNetwork, ...] = TRUSTED_PROXY_NETWORKS,
) -> str | None:
    """Resolve source IP without accepting forwarding headers from arbitrary peers."""
    client = scope.get("client")
    direct_host = str(client[0]) if client else ""
    if not _is_trusted_proxy(direct_host, trusted_proxies):
        return direct_host[:45] or None

    real_ip = _parsed_ip(headers.get("x-real-ip", ""))
    if real_ip is not None:
        return str(real_ip)

    forwarded = headers.get("x-forwarded-for", "")
    parsed_chain = [
        address
        for part in forwarded.split(",")
        if (address := _parsed_ip(part)) is not None
    ]
    for address in reversed(parsed_chain):
        if not _is_trusted_proxy(str(address), trusted_proxies):
            return str(address)
    if parsed_chain:
        return str(parsed_chain[0])
    return direct_host[:45] or None


class AnonymousAuditLimiter:
    """Fixed-window per-source limiter with bounded LRU source tracking."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        max_sources: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._validate(limit, window_seconds, max_sources)
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_sources = max_sources
        self.clock = clock
        self._windows: OrderedDict[str, tuple[float, int]] = OrderedDict()

    @staticmethod
    def _validate(limit: int, window_seconds: float, max_sources: int) -> None:
        if limit < 1 or window_seconds <= 0 or max_sources < 1:
            raise ValueError("Audit rate-limit settings must be positive")

    @property
    def source_count(self) -> int:
        return len(self._windows)

    def reset(
        self,
        *,
        limit: int | None = None,
        window_seconds: float | None = None,
        max_sources: int | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        next_limit = limit if limit is not None else self.limit
        next_window = (
            window_seconds if window_seconds is not None else self.window_seconds
        )
        next_max_sources = max_sources if max_sources is not None else self.max_sources
        self._validate(next_limit, next_window, next_max_sources)
        self.limit = next_limit
        self.window_seconds = next_window
        self.max_sources = next_max_sources
        if clock is not None:
            self.clock = clock
        self._windows.clear()

    def allow(self, source: str | None) -> bool:
        key = source or "unknown"
        now = self.clock()
        current = self._windows.pop(key, None)
        if current is None or now - current[0] >= self.window_seconds:
            window = (now, 1)
            allowed = True
        else:
            window = (current[0], current[1] + 1)
            allowed = window[1] <= self.limit
        self._windows[key] = window
        while len(self._windows) > self.max_sources:
            self._windows.popitem(last=False)
        return allowed


def redact(value: Any, depth: int = 0) -> Any:
    """Recursively remove secret and binary-like values from JSON-compatible data."""
    if depth >= 20:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(key): REDACTED
            if _SENSITIVE_KEY.search(str(key))
            else redact(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value[:100]]
    if isinstance(value, str) and len(value) > 2_000:
        return value[:2_000] + "[TRUNCATED]"
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")


def build_summary(
    *,
    body: bytes,
    body_truncated: bool,
    content_type: str,
    content_length: int | None,
) -> str:
    media_type = content_type.partition(";")[0].strip().lower()
    if media_type == "multipart/form-data":
        value = {
            "upload": {
                "content_type": media_type,
                "content_length": content_length or 0,
            }
        }
    elif body_truncated:
        value = {
            "request": {
                "_truncated": True,
                "body_bytes": content_length or len(body),
            }
        }
    elif media_type == "application/json" and body:
        try:
            value = {"request": redact(json.loads(body))}
        except (UnicodeDecodeError, json.JSONDecodeError):
            value = {"request": {"_invalid_json": True}}
    else:
        value = {"request": {}}

    serialized = _json_bytes(value)
    if len(serialized) > MAX_SUMMARY_BYTES:
        serialized = _json_bytes(
            {
                "request": {
                    "_truncated": True,
                    "body_bytes": content_length or len(body),
                }
            }
        )
    return serialized.decode("utf-8")


def write_audit_log(entry: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        db.add(AuditLog(**entry))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_STOP = object()


class AuditQueue:
    """One bounded queue and daemon worker for best-effort audit persistence."""

    def __init__(
        self,
        *,
        max_queue_size: int = AUDIT_QUEUE_SIZE,
        write_func: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if max_queue_size < 1:
            raise ValueError("Audit queue size must be positive")
        self.max_queue_size = max_queue_size
        self._write_func = write_func
        self._queue: queue.Queue | None = None
        self._worker_thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._accepting = False
        self._lifecycle_lock = threading.Lock()

    @property
    def pending_count(self) -> int:
        return self._queue.qsize() if self._queue is not None else 0

    async def start(self) -> None:
        with self._lifecycle_lock:
            if (
                self._accepting
                and self._worker_thread is not None
                and self._worker_thread.is_alive()
            ):
                return

            if self._queue is not None:
                dropped = self._discard_pending(self._queue)
                if dropped:
                    logger.warning(
                        "Audit worker restart discarded %d pending entries", dropped
                    )

            work_queue: queue.Queue = queue.Queue(maxsize=self.max_queue_size)
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._worker,
                args=(work_queue, stop_event),
                name="audit-persistence-worker",
                daemon=True,
            )
            self._queue = work_queue
            self._stop_event = stop_event
            self._worker_thread = worker
            self._accepting = True
            worker.start()

    def enqueue(self, entry: dict[str, Any]) -> bool:
        with self._lifecycle_lock:
            work_queue = self._queue
            worker = self._worker_thread
            if (
                not self._accepting
                or work_queue is None
                or worker is None
                or not worker.is_alive()
            ):
                logger.warning("Audit worker unavailable; dropping newest entry")
                return False
            try:
                work_queue.put_nowait(entry)
            except queue.Full:
                logger.warning("Audit queue full; dropping newest entry")
                return False
            return True

    async def drain(self) -> None:
        work_queue = self._queue
        if work_queue is not None:
            await self._wait_for_drain(work_queue)

    async def stop(self, timeout: float = 5.0) -> None:
        timeout = max(timeout, 0.0)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        with self._lifecycle_lock:
            work_queue = self._queue
            worker = self._worker_thread
            stop_event = self._stop_event
            self._accepting = False

        if work_queue is None or worker is None or stop_event is None:
            return

        try:
            drained = await self._wait_for_drain(work_queue, deadline=deadline)
            stop_event.set()
            if not drained:
                dropped = self._discard_pending(work_queue)
                logger.warning(
                    "Audit queue drain timeout; discarded %d pending entries",
                    dropped,
                )
            elif worker.is_alive():
                work_queue.put_nowait(_STOP)

            await self._wait_for_thread(worker, deadline=deadline)
            if worker.is_alive():
                logger.warning(
                    "Audit worker did not stop before timeout; "
                    "abandoning bounded daemon worker"
                )
        finally:
            dropped = self._discard_pending(work_queue)
            if dropped:
                logger.warning(
                    "Audit queue stop discarded %d pending entries", dropped
                )
            with self._lifecycle_lock:
                if self._queue is work_queue:
                    self._queue = None
                    self._worker_thread = None
                    self._stop_event = None

    @staticmethod
    def _discard_pending(work_queue: queue.Queue) -> int:
        dropped = 0
        while True:
            try:
                work_queue.get_nowait()
            except queue.Empty:
                return dropped
            else:
                work_queue.task_done()
                dropped += 1

    @staticmethod
    async def _wait_for_drain(
        work_queue: queue.Queue, *, deadline: float | None = None
    ) -> bool:
        loop = asyncio.get_running_loop()
        while True:
            with work_queue.all_tasks_done:
                if work_queue.unfinished_tasks == 0:
                    return True
            if deadline is not None and loop.time() >= deadline:
                return False
            await asyncio.sleep(0.001)

    @staticmethod
    async def _wait_for_thread(
        worker: threading.Thread, *, deadline: float
    ) -> None:
        loop = asyncio.get_running_loop()
        while worker.is_alive() and loop.time() < deadline:
            await asyncio.sleep(0.001)

    def _worker(
        self,
        work_queue: queue.Queue,
        stop_event: threading.Event,
    ) -> None:
        while True:
            try:
                entry = work_queue.get(timeout=0.1)
            except queue.Empty:
                if stop_event.is_set():
                    return
                continue
            try:
                if entry is _STOP:
                    return
                writer = self._write_func or write_audit_log
                writer(entry)
            except Exception:
                logger.exception("Unable to persist audit log")
            finally:
                work_queue.task_done()
            if stop_event.is_set():
                return


audit_queue = AuditQueue()
anonymous_audit_limiter = AnonymousAuditLimiter(
    limit=ANONYMOUS_AUDIT_LIMIT,
    window_seconds=ANONYMOUS_AUDIT_WINDOW_SECONDS,
    max_sources=ANONYMOUS_AUDIT_MAX_SOURCES,
)


async def drain_audit_logs() -> None:
    """Wait until all accepted audit writes finish; intended for deterministic tests."""
    await audit_queue.drain()


def reset_anonymous_audit_limiter_for_tests(
    *,
    limit: int,
    window_seconds: float,
    max_sources: int,
    clock: Callable[[], float],
) -> None:
    anonymous_audit_limiter.reset(
        limit=limit,
        window_seconds=window_seconds,
        max_sources=max_sources,
        clock=clock,
    )


def _reset_anonymous_audit_limiter() -> None:
    anonymous_audit_limiter.reset(
        limit=ANONYMOUS_AUDIT_LIMIT,
        window_seconds=ANONYMOUS_AUDIT_WINDOW_SECONDS,
        max_sources=ANONYMOUS_AUDIT_MAX_SOURCES,
        clock=time.monotonic,
    )


def _resource(scope: dict[str, Any]) -> str:
    parts = [part for part in scope.get("path", "").split("/") if part]
    if parts and parts[0] == "api":
        parts.pop(0)
    if parts and parts[0] == "integration":
        parts.pop(0)
    resource = parts[0] if parts else "unknown"
    return "supplier" if resource == "suppliers" else resource[:100]


def _resource_id(scope: dict[str, Any], response_body: bytes) -> str | None:
    path_params = scope.get("path_params", {})
    for name, value in path_params.items():
        if name.endswith("_id") or name in {"id", "sku"}:
            return str(value)[:255]

    if response_body:
        try:
            response = json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(response, dict):
            for name in ("id", "transaksi_id", "barang_id"):
                value = response.get(name)
                if isinstance(value, (str, int)):
                    return str(value)[:255]
    return None


class AuditMiddleware:
    """Tee mutation traffic while forwarding request/response streams unchanged."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "lifespan":
            _reset_anonymous_audit_limiter()
            await audit_queue.start()
            try:
                await self.app(scope, receive, send)
            finally:
                await audit_queue.stop()
            return

        method = scope.get("method", "").upper()
        if scope.get("type") != "http" or method not in AUDITED_METHODS:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        content_type = headers.get("content-type", "")
        multipart = content_type.lower().startswith("multipart/form-data")
        content_length_text = headers.get("content-length", "")
        try:
            content_length = int(content_length_text) if content_length_text else None
        except (ValueError, TypeError):
            content_length = None
        request_body = bytearray()
        request_truncated = bool(
            content_length and content_length > MAX_CAPTURE_BYTES
        )
        response_body = bytearray()
        response_json = False
        capture_response = _resource(scope) != "auth"
        status_code = 500

        async def audit_receive():
            nonlocal request_truncated
            message = await receive()
            chunk = message.get("body", b"")
            if chunk and not multipart and not request_truncated:
                remaining = MAX_CAPTURE_BYTES - len(request_body)
                request_body.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    request_truncated = True
            return message

        async def audit_send(message):
            nonlocal response_json, status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = {
                    key.decode("latin-1").lower(): value.decode("latin-1")
                    for key, value in message.get("headers", [])
                }
                response_json = capture_response and response_headers.get(
                    "content-type", ""
                ).lower().startswith("application/json")
            elif message["type"] == "http.response.body" and response_json:
                chunk = message.get("body", b"")
                remaining = MAX_CAPTURE_BYTES - len(response_body)
                if remaining > 0:
                    response_body.extend(chunk[:remaining])
            await send(message)

        try:
            await self.app(scope, audit_receive, audit_send)
        finally:
            try:
                if status_code != 405 and scope.get("route") is not None:
                    path = scope.get("path", "")
                    state = scope.get("state", {})
                    audit_override = state.get("audit_override")
                    should_audit = not state.get("audit_skip") and not (
                        path.startswith("/api/chatbot") and audit_override is None
                    )
                    source_ip = None
                    if should_audit:
                        audit_override = audit_override or {}
                        source_ip = client_ip(scope, headers)
                        is_anonymous = (
                            state.get("audit_user_id") is None
                            and state.get("audit_username") is None
                        )
                        if is_anonymous and not anonymous_audit_limiter.allow(
                            source_ip
                        ):
                            logger.warning(
                                "Anonymous audit rate limit exceeded for IP %s",
                                source_ip,
                            )
                            should_audit = False
                    if should_audit:
                        summary = audit_override.get("summary")
                        if summary is not None:
                            serialized_summary = _json_bytes(redact(summary))
                            if len(serialized_summary) > MAX_SUMMARY_BYTES:
                                serialized_summary = _json_bytes(
                                    {
                                        "request": {
                                            "_truncated": True,
                                            "body_bytes": content_length
                                            or len(request_body),
                                        }
                                    }
                                )
                            summary = serialized_summary.decode("utf-8")
                        else:
                            summary = build_summary(
                                body=bytes(request_body),
                                body_truncated=request_truncated,
                                content_type=content_type,
                                content_length=content_length,
                            )
                        entry = {
                            "user_id": state.get("audit_user_id"),
                            "username": state.get("audit_username"),
                            "action": audit_override.get(
                                "action", AUDITED_METHODS[method]
                            ),
                            "http_method": method,
                            "resource": audit_override.get(
                                "resource", _resource(scope)
                            ),
                            "resource_id": audit_override.get(
                                "resource_id",
                                _resource_id(scope, bytes(response_body)),
                            ),
                            "path": path[:500],
                            "status_code": status_code,
                            "ip_address": source_ip,
                            "summary": summary,
                        }
                        audit_queue.enqueue(entry)
            except Exception:
                logger.exception("Unable to enqueue audit log")
