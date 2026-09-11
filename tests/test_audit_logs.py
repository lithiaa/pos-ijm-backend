import json
import asyncio
import subprocess
import sys
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateTable
from sqlalchemy import text

from app.auth import create_access_token
from app.models.audit_log import AuditLog
from app.models.barang import Barang
from app.models.transaksi import StokSaatIni
from app.models.user import User
from tests.conftest import TEST_INTEGRATION_KEY


def authenticate(client, db, username="audit-user", role="admin"):
    user = User(
        username=username,
        password_hash="unused",
        nama="Audit User",
        role=role,
    )
    db.add(user)
    db.commit()
    client.headers["Authorization"] = (
        f"Bearer {create_access_token({'sub': str(user.id)})}"
    )
    return user


def drain_audits(client):
    from app.audit import drain_audit_logs

    client.portal.call(drain_audit_logs)


def audit_rows(client, db):
    drain_audits(client)
    db.expire_all()
    return db.execute(
        text("SELECT * FROM audit_logs ORDER BY id ASC")
    ).mappings().all()


async def wait_for_thread_event(event, timeout=1.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not event.is_set():
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.001)
    return True


def test_audit_log_model_defaults_to_utc_on_mysql_and_sqlite():
    mysql_ddl = str(CreateTable(AuditLog.__table__).compile(dialect=mysql.dialect()))
    sqlite_ddl = str(CreateTable(AuditLog.__table__).compile(dialect=sqlite.dialect()))

    assert "created_at DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP())" in mysql_ddl
    assert "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL" in sqlite_ddl


def test_created_at_serialization_treats_naive_database_values_as_utc_and_normalizes_aware_values():
    from app.routers.logs import _created_at

    naive_utc = datetime(2026, 9, 9, 2, 3, 4)
    aware_utc_plus_eight = datetime(
        2026, 9, 9, 10, 3, 4, tzinfo=timezone(timedelta(hours=8))
    )

    assert _created_at(naive_utc) == "2026-09-09T02:03:04Z"
    assert _created_at(aware_utc_plus_eight) == "2026-09-09T02:03:04Z"


def test_bearer_create_records_actor_object_and_recursively_redacted_summary(
    client, db
):
    user = authenticate(client, db)
    bearer = client.headers["Authorization"]
    response = client.post(
        "/api/barang",
        headers={"X-Real-IP": "203.0.113.8"},
        json={
            "sku": "AUDIT-001",
            "nama": "Audit brake pad",
            "stok_awal": 0,
            "foto": "raw-photo-must-not-survive",
        },
    )

    assert response.status_code == 200
    rows = audit_rows(client, db)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == user.id
    assert row["username"] == user.username
    assert row["action"] == "CREATE"
    assert row["http_method"] == "POST"
    assert row["resource"] == "barang"
    assert row["resource_id"] == str(response.json()["id"])
    assert row["path"] == "/api/barang"
    assert row["status_code"] == 200
    assert row["ip_address"] == "testclient"
    assert row["created_at"] is not None

    serialized = row["summary"]
    summary = json.loads(serialized)
    assert summary["request"]["sku"] == "AUDIT-001"
    assert summary["request"]["foto"] == "[REDACTED]"
    for forbidden in (
        "raw-photo-must-not-survive",
        bearer,
    ):
        assert forbidden not in serialized


def test_redaction_is_recursive_and_matches_secret_like_keys():
    from app.audit import redact

    value = {
        "safe": [{"label": "kept", "access_token": "hidden-token"}],
        "clientSecret": "hidden-secret",
        "password_confirmation": "hidden-password",
        "api_key": "hidden-key",
        "Cookie": "hidden-cookie",
        "authorization": "hidden-authorization",
        "photoBase64": "hidden-photo",
    }

    redacted = redact(value)

    assert redacted["safe"] == [{"label": "kept", "access_token": "[REDACTED]"}]
    assert all(
        redacted[key] == "[REDACTED]"
        for key in value
        if key != "safe"
    )


def test_forwarded_ip_headers_are_ignored_from_an_untrusted_direct_client():
    from app.audit import client_ip

    scope = {"client": ("198.51.100.12", 4321)}
    headers = {
        "x-real-ip": "203.0.113.8",
        "x-forwarded-for": "192.0.2.9, 192.0.2.10",
    }

    assert client_ip(scope, headers) == "198.51.100.12"


def test_forwarded_ip_is_accepted_only_from_loopback_or_an_explicit_trusted_proxy():
    from app.audit import client_ip, parse_trusted_proxy_networks

    loopback_scope = {"client": ("127.0.0.1", 4321)}
    explicit_proxy_scope = {"client": ("10.20.30.40", 4321)}

    assert client_ip(
        loopback_scope,
        {"x-real-ip": "203.0.113.8", "x-forwarded-for": "192.0.2.9"},
    ) == "203.0.113.8"
    assert client_ip(
        explicit_proxy_scope,
        {"x-forwarded-for": "192.0.2.9, 10.20.30.41"},
        parse_trusted_proxy_networks("10.20.30.0/24"),
    ) == "192.0.2.9"


def test_integration_mutation_uses_integration_actor_and_path_object_id(client, db):
    barang = Barang(sku="INTEGRATION-AUDIT", nama="Before", harga_jual=100)
    db.add(barang)
    db.flush()
    db.add(StokSaatIni(barang_id=barang.id, jumlah=1))
    db.commit()

    response = client.put(
        f"/api/integration/barang/{barang.id}",
        headers={"X-Integration-Key": TEST_INTEGRATION_KEY},
        json={"nama": "After"},
    )

    assert response.status_code == 200
    row = audit_rows(client, db)[0]
    assert row["user_id"] is None
    assert row["username"] == "integration"
    assert row["action"] == "UPDATE"
    assert row["resource"] == "barang"
    assert row["resource_id"] == str(barang.id)
    assert row["status_code"] == 200
    assert TEST_INTEGRATION_KEY not in row["summary"]


def test_failed_mutation_is_logged_but_reads_are_not(client, db):
    failed = client.post(
        "/api/integration/barang",
        headers={"X-Integration-Key": "wrong-integration-secret"},
        json={"nama": "Rejected", "api_key": "body-key-must-not-survive"},
    )
    assert failed.status_code == 401
    assert client.get("/api/integration/barang").status_code == 401
    assert client.options("/api/integration/barang").status_code in (200, 405)

    rows = audit_rows(client, db)
    assert len(rows) == 1
    assert rows[0]["status_code"] == 401
    assert rows[0]["action"] == "CREATE"
    assert rows[0]["username"] is None
    assert "wrong-integration-secret" not in rows[0]["summary"]
    assert "body-key-must-not-survive" not in rows[0]["summary"]


def test_login_never_persists_password_or_returned_access_token(
    client, db, monkeypatch
):
    authenticate(client, db, username="login-audit")
    client.headers.pop("Authorization")
    monkeypatch.setattr("app.routers.auth.verify_password", lambda *_: True)

    response = client.post(
        "/api/auth/login",
        json={"username": "login-audit", "password": "login-password"},
    )

    assert response.status_code == 200
    serialized = audit_rows(client, db)[0]["summary"]
    assert json.loads(serialized)["request"]["password"] == "[REDACTED]"
    assert "login-password" not in serialized
    assert response.json()["access_token"] not in serialized


def test_summary_is_bounded_and_valid_json(client, db):
    authenticate(client, db)
    response = client.post(
        "/api/barang",
        json={"sku": "BIG-SUMMARY", "nama": "x" * 20_000, "stok_awal": 0},
    )
    assert response.status_code == 200

    summary = audit_rows(client, db)[0]["summary"]
    assert len(summary.encode("utf-8")) <= 8_192
    assert json.loads(summary)["request"]["_truncated"] is True


def test_multipart_audit_stores_metadata_not_file_bytes(
    client, db, tmp_path, monkeypatch
):
    monkeypatch.setattr("app.routers.upload.STORAGE_DIR", str(tmp_path))
    barang = Barang(sku="UPLOAD-AUDIT", nama="Upload")
    db.add(barang)
    db.commit()
    marker = b"binary-marker-must-not-survive"

    response = client.post(
        f"/api/upload/foto/{barang.id}",
        files={"file": ("audit.jpg", marker, "image/jpeg")},
    )

    assert response.status_code == 200
    summary = audit_rows(client, db)[0]["summary"]
    metadata = json.loads(summary)["upload"]
    assert metadata["content_type"] == "multipart/form-data"
    assert metadata["content_length"] > len(marker)
    assert marker.decode() not in summary
    assert "audit.jpg" not in summary


def test_unknown_and_method_not_allowed_mutations_are_not_logged_but_valid_route_404_is(
    client, db
):
    authenticate(client, db)

    assert client.post("/api/not-a-real-route", json={}).status_code == 404
    assert client.post("/api/supplier/123", json={}).status_code == 405
    assert client.put("/api/supplier/123", json={}).status_code == 404

    rows = audit_rows(client, db)
    assert [(row["path"], row["status_code"]) for row in rows] == [
        ("/api/supplier/123", 404)
    ]


def test_valid_route_validation_failure_is_logged(client, db):
    authenticate(client, db)

    response = client.post("/api/supplier", json={})

    assert response.status_code == 422
    rows = audit_rows(client, db)
    assert len(rows) == 1
    assert rows[0]["path"] == "/api/supplier"
    assert rows[0]["status_code"] == 422
    assert rows[0]["username"] == "audit-user"


def test_anonymous_failures_are_rate_limited_per_source_with_deterministic_time_reset(
    client, db
):
    from app.audit import reset_anonymous_audit_limiter_for_tests

    now = [100.0]
    reset_anonymous_audit_limiter_for_tests(
        limit=2,
        window_seconds=10.0,
        max_sources=2,
        clock=lambda: now[0],
    )
    request = lambda: client.post(
        "/api/integration/barang",
        headers={
            "X-Integration-Key": "wrong",
            "X-Forwarded-For": "203.0.113.99",
        },
        json={"nama": "rejected"},
    )

    assert [request().status_code for _ in range(3)] == [401, 401, 401]
    assert len(audit_rows(client, db)) == 2

    now[0] += 10.0
    assert request().status_code == 401
    assert len(audit_rows(client, db)) == 3


def test_anonymous_audit_limiter_has_bounded_source_state_and_can_reset():
    from app.audit import AnonymousAuditLimiter

    now = [50.0]
    limiter = AnonymousAuditLimiter(
        limit=1,
        window_seconds=5.0,
        max_sources=2,
        clock=lambda: now[0],
    )
    assert limiter.allow("source-a") is True
    assert limiter.allow("source-a") is False
    assert limiter.allow("source-b") is True
    assert limiter.allow("source-c") is True
    assert limiter.source_count == 2
    limiter.reset(clock=lambda: 100.0)
    assert limiter.source_count == 0
    assert limiter.allow("source-a") is True


def test_chatbot_logs_only_committed_create_update_and_delete(client, db):
    created = client.post(
        "/api/chatbot/",
        json={"command": "tambah barang nama=Chatbot Audit harga_jual=1000"},
    )
    assert created.status_code == 200
    barang_id = int(created.json()["response"].split("ID: ", 1)[1].rstrip(")"))

    updated = client.post(
        "/api/chatbot/",
        json={"command": f"ubah barang id={barang_id} nama=Chatbot Updated"},
    )
    deleted = client.post(
        "/api/chatbot/",
        json={"command": f"hapus barang id={barang_id}"},
    )

    assert updated.status_code == 200
    assert deleted.status_code == 200
    rows = audit_rows(client, db)
    assert [
        (row["action"], row["resource"], row["resource_id"])
        for row in rows
    ] == [
        ("CREATE", "barang", str(barang_id)),
        ("UPDATE", "barang", str(barang_id)),
        ("DELETE", "barang", str(barang_id)),
    ]
    assert json.loads(rows[0]["summary"])["request"] == {
        "nama": "Chatbot Audit",
        "harga_jual": "1000",
    }


def test_chatbot_search_unknown_validation_failure_and_noop_are_not_logged(
    client, db
):
    barang = Barang(sku="CHATBOT-NOOP", nama="Unchanged", harga_jual=100)
    db.add(barang)
    db.commit()

    responses = [
        client.post("/api/chatbot/", json={"command": "cari barang nama=Unchanged"}),
        client.post("/api/chatbot/", json={"command": "perintah misterius"}),
        client.post("/api/chatbot/", json={"command": "tambah barang"}),
        client.post(
            "/api/chatbot/",
            json={"command": f"ubah barang id={barang.id} nama=Unchanged"},
        ),
        client.post(
            "/api/chatbot/",
            json={"command": f"ubah barang id={barang.id} stok_minimum=5"},
        ),
        client.post("/api/chatbot/", json={}),
    ]

    assert [response.status_code for response in responses] == [
        200,
        200,
        200,
        200,
        200,
        422,
    ]
    assert audit_rows(client, db) == []


def test_successful_anonymous_chatbot_audits_are_rate_limited_per_source(
    client, db
):
    from app.audit import reset_anonymous_audit_limiter_for_tests

    reset_anonymous_audit_limiter_for_tests(
        limit=2,
        window_seconds=60.0,
        max_sources=2,
        clock=lambda: 100.0,
    )

    responses = [
        client.post(
            "/api/chatbot/",
            json={"command": f"tambah barang nama=Bounded {index}"},
        )
        for index in range(3)
    ]

    assert all(response.status_code == 200 for response in responses)
    assert db.query(Barang).filter(Barang.nama.like("Bounded %")).count() == 3
    assert len(audit_rows(client, db)) == 2


def test_skipped_chatbot_audit_does_not_suppress_downstream_exception():
    from app.audit import AuditMiddleware

    async def failing_app(scope, _receive, _send):
        scope["state"]["audit_skip"] = True
        raise RuntimeError("skipped chatbot failed")

    async def exercise_middleware():
        middleware = AuditMiddleware(failing_app)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/chatbot/",
            "headers": [],
            "state": {},
            "route": object(),
            "client": ("203.0.113.10", 1234),
        }

        with pytest.raises(RuntimeError, match="skipped chatbot failed"):
            await middleware(scope, None, None)

    asyncio.run(exercise_middleware())


def test_rate_limited_anonymous_audit_does_not_suppress_downstream_exception(
    monkeypatch,
):
    from app.audit import AuditMiddleware, anonymous_audit_limiter

    monkeypatch.setattr(anonymous_audit_limiter, "allow", lambda _source: False)

    async def failing_app(_scope, _receive, _send):
        raise RuntimeError("rate-limited anonymous request failed")

    async def exercise_middleware():
        middleware = AuditMiddleware(failing_app)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/supplier",
            "headers": [],
            "state": {},
            "route": object(),
            "client": ("203.0.113.11", 1234),
        }

        with pytest.raises(
            RuntimeError, match="rate-limited anonymous request failed"
        ):
            await middleware(scope, None, None)

    asyncio.run(exercise_middleware())


def test_audit_write_failure_never_changes_business_response(
    client, db, monkeypatch, caplog
):
    authenticate(client, db)
    from app import audit

    def fail_write(_entry):
        raise RuntimeError("audit database unavailable")

    monkeypatch.setattr(audit, "write_audit_log", fail_write)
    response = client.post(
        "/api/supplier", json={"nama": "Business request still commits"}
    )

    assert response.status_code == 200
    assert response.json()["nama"] == "Business request still commits"
    drain_audits(client)
    assert "Unable to persist audit log" in caplog.text


def test_slow_audit_write_does_not_delay_business_response(client, db, monkeypatch):
    authenticate(client, db)
    from app import audit

    release = threading.Event()
    original_write = audit.write_audit_log

    def slow_write(entry):
        release.wait(timeout=0.5)
        original_write(entry)

    monkeypatch.setattr(audit, "write_audit_log", slow_write)
    timer = threading.Timer(0.5, release.set)
    timer.start()
    started_at = time.perf_counter()
    try:
        response = client.post("/api/supplier", json={"nama": "Fast response"})
        elapsed = time.perf_counter() - started_at
        assert response.status_code == 200
        assert elapsed < 0.3
    finally:
        release.set()
        timer.cancel()
    assert len(audit_rows(client, db)) == 1


def test_audit_queue_overflow_is_bounded_and_drops_newest(caplog):
    from app.audit import AuditQueue

    started = threading.Event()
    release = threading.Event()
    persisted = []

    def blocked_write(entry):
        started.set()
        release.wait(timeout=2)
        persisted.append(entry["sequence"])

    async def exercise_queue():
        queue = AuditQueue(max_queue_size=1, write_func=blocked_write)
        await queue.start()
        try:
            assert queue.enqueue({"sequence": 1}) is True
            assert await wait_for_thread_event(started) is True
            assert queue.enqueue({"sequence": 2}) is True
            assert queue.enqueue({"sequence": 3}) is False
            assert queue.pending_count == 1
            release.set()
            await queue.drain()
        finally:
            release.set()
            await queue.stop()

    asyncio.run(exercise_queue())
    assert persisted == [1, 2]
    assert "Audit queue full; dropping newest entry" in caplog.text


def test_audit_queue_rejects_missing_and_stopped_workers():
    from app.audit import AuditQueue

    async def exercise_queue():
        queue = AuditQueue(max_queue_size=1)
        assert queue.enqueue({"sequence": 0}) is False

        await queue.start()
        worker = queue._worker_thread
        assert worker is not None
        assert worker.daemon is True
        await asyncio.wait_for(queue.stop(timeout=0.1), timeout=0.2)

        assert queue.enqueue({"sequence": 1}) is False
        assert queue.pending_count == 0
        assert queue._queue is None
        assert queue._worker_thread is None

    asyncio.run(exercise_queue())


def test_audit_queue_stop_is_bounded_when_writer_hangs_and_discards_pending():
    from app.audit import AuditQueue

    started = threading.Event()
    release = threading.Event()

    def hung_write(_entry):
        started.set()
        release.wait(timeout=2)

    async def exercise_queue():
        queue = AuditQueue(max_queue_size=1, write_func=hung_write)
        await queue.start()
        try:
            assert queue.enqueue({"sequence": 1}) is True
            assert await wait_for_thread_event(started) is True
            assert queue.enqueue({"sequence": 2}) is True
            raw_queue = queue._queue
            worker = queue._worker_thread
            assert worker is not None
            assert worker.daemon is True

            started_at = asyncio.get_running_loop().time()
            await asyncio.wait_for(queue.stop(timeout=0.02), timeout=0.2)
            assert asyncio.get_running_loop().time() - started_at < 0.2
            assert raw_queue.empty()
            assert queue.pending_count == 0
            assert queue._queue is None
            assert queue._worker_thread is None
        finally:
            release.set()
        while worker.is_alive():
            await asyncio.sleep(0.001)
        raw_queue.join()

    asyncio.run(exercise_queue())


def test_permanently_blocked_audit_writer_does_not_prevent_process_exit():
    script = """
import asyncio
import threading

from app.audit import AuditQueue

started = threading.Event()

def blocked_forever(_entry):
    started.set()
    threading.Event().wait()

async def main():
    queue = AuditQueue(max_queue_size=1, write_func=blocked_forever)
    await queue.start()
    assert queue.enqueue({"sequence": 1}) is True
    while not started.is_set():
        await asyncio.sleep(0.001)
    await queue.stop(timeout=0.02)
    print("bounded stop returned", flush=True)

asyncio.run(main())
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "bounded stop returned\n"


def test_audit_summary_failure_never_changes_business_response(
    client, db, monkeypatch
):
    authenticate(client, db)
    from app import audit

    def fail_summary(**_values):
        raise RuntimeError("summary failed")

    monkeypatch.setattr(audit, "build_summary", fail_summary)
    response = client.post(
        "/api/supplier", json={"nama": "Summary failure is isolated"}
    )

    assert response.status_code == 200
    assert response.json()["nama"] == "Summary failure is isolated"
    drain_audits(client)


def test_logs_api_is_authenticated_read_only_paginated_and_filterable(client, db):
    earliest_created_at = datetime.now(timezone.utc).replace(microsecond=0)
    authenticate(client, db, username="reader")
    client.post("/api/supplier", json={"nama": "Alpha supplier"})
    client.post("/api/supplier", json={"nama": "Beta supplier"})

    unauthorized_headers = {"Authorization": "Bearer invalid"}
    assert client.get("/api/logs", headers=unauthorized_headers).status_code == 401
    for method in ("post", "put", "patch", "delete"):
        assert client.request(method.upper(), "/api/logs", json={}).status_code == 405

    response = client.get(
        "/api/logs",
        params={
            "q": "Beta",
            "action": "CREATE",
            "resource": "supplier",
            "user": "reader",
            "date_from": "2000-01-01",
            "date_to": datetime.now(timezone.utc).date().isoformat(),
            "sort_by": "created_at",
            "sort_order": "DESC",
            "page": 1,
            "limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["limit"] == 1
    assert len(payload["data"]) == 1
    record = payload["data"][0]
    assert record["resource"] == "supplier"
    assert record["action"] == "CREATE"
    assert record["username"] == "reader"
    assert record["summary"]["request"]["nama"] == "Beta supplier"
    returned_created_at = datetime.fromisoformat(
        record["created_at"].replace("Z", "+00:00")
    )
    assert earliest_created_at <= returned_created_at <= datetime.now(timezone.utc)

    invalid_sort = client.get("/api/logs", params={"sort_by": "summary"})
    assert invalid_sort.status_code == 422


def test_logs_api_rejects_authenticated_non_admin(client, db):
    authenticate(client, db, username="employee", role="karyawan")

    response = client.get("/api/logs")

    assert response.status_code == 403
