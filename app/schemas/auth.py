from pydantic import BaseModel


class TwoFactorVerifyRequest(BaseModel):
    firebase_token: str
