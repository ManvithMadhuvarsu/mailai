from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PreferenceUpdateRequest(BaseModel):
    mode: str = Field(pattern="^(labels_only|drafts)$")
    poll_interval_minutes: int = Field(ge=5, le=1440)
    paused: bool = False

