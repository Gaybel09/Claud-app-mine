from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


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
