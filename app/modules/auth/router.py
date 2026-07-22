from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core import firebase
from app.core.security import get_current_user, get_verified_token
from app.db.session import get_db
from app.models.cube import create_starter_cube
from app.models.user import User
from app.schemas.auth import TwoFactorVerifyRequest
from app.schemas.user import UserRegister, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegister,
    decoded_token: dict = Depends(get_verified_token),
    db: Session = Depends(get_db),
):
    firebase_uid = decoded_token.get("uid")
    email = decoded_token.get("email")
    if not firebase_uid or not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing uid or email claim")

    if db.query(User).filter(User.firebase_uid == firebase_uid).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "User already registered")

    user = User(firebase_uid=firebase_uid, email=email, phone=payload.phone, pix_key=payload.pix_key)
    db.add(user)
    db.flush()  # popula user.id para o cubo inicial referenciar via FK

    # PRD: usuário ganha um cubo comum ao se registrar.
    db.add(create_starter_cube(user.id))

    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=UserRead)
def login(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/2fa/verify")
def verify_2fa(
    payload: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        decoded_token = firebase.verify_firebase_token(payload.firebase_token)
    except firebase.InvalidFirebaseTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired 2FA token")

    phone_number = decoded_token.get("phone_number")
    if not phone_number or phone_number != current_user.phone:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "2FA token does not match registered phone")

    return {"verified": True}
