from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    phone: str | None = None
    pix_key: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    phone: str | None
    pix_key: str | None
    kyc_status: str
    created_at: datetime
    is_blocked: bool
    nickname: str | None
    country_code: str | None
    state_code: str | None


class NicknameUpdate(BaseModel):
    nickname: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9À-ÖØ-öø-ÿ _-]+$")
