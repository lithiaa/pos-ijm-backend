from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class InvitationAccept(BaseModel):
    token: str
    password: str

    @property
    def valid_password(self) -> bool:
        return len(self.password) >= 10
