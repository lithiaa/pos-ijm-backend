from pydantic import BaseModel, ConfigDict, Field, field_validator


class AdministratorInvitation(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    username: str = Field(min_length=3, max_length=50)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or not all(value.split("@")):
            raise ValueError("Invalid email")
        return value


class EnvironmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    administrator: AdministratorInvitation


class SupportGrantCreate(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)
    duration_minutes: int = Field(ge=5, le=480)


class EnvironmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
    business_type: str | None = Field(None, max_length=100)
    logo_url: str | None = Field(None, max_length=500)
    address: str | None = Field(None, max_length=500)
    phone: str | None = Field(None, max_length=50)
    timezone: str | None = Field(None, min_length=1, max_length=100)
    currency: str | None = Field(None, min_length=3, max_length=10)
