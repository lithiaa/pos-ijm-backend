from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth import ALL_PERMISSIONS


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    username: str = Field(min_length=3, max_length=50)
    role: Literal["staff", "viewer"]
    permissions: list[str] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or not all(value.split("@")):
            raise ValueError("Invalid email")
        return value

    @field_validator("permissions")
    @classmethod
    def allowlisted_permissions(cls, value: list[str]) -> list[str]:
        if any(permission not in ALL_PERMISSIONS for permission in value):
            raise ValueError("Unknown permission")
        if any(permission.startswith("users.") or permission == "environment.settings" for permission in value):
            raise ValueError("Permission reserved for administrators")
        return sorted(set(value))


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
    role: Literal["staff", "viewer"] | None = None
    permissions: list[str] | None = None

    _validate_permissions = field_validator("permissions")(UserCreate.allowlisted_permissions.__func__)
