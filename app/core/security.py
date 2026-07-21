from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import firebase
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_verified_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        return firebase.verify_firebase_token(credentials.credentials)
    except firebase.InvalidFirebaseTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


def get_current_user(
    decoded_token: dict = Depends(get_verified_token),
    db: Session = Depends(get_db),
) -> User:
    email = decoded_token.get("email")
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing email claim")
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not registered")
    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is blocked")
    return user
