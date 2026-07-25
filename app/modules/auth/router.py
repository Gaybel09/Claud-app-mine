from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core import firebase
from app.core.rate_limit import (
    LOGIN_LIMIT_PER_IP,
    LOGIN_LIMIT_PER_TOKEN,
    REGISTER_LIMIT_PER_IP,
    REGISTER_LIMIT_PER_TOKEN,
    get_auth_token_key,
    limiter,
)
from app.core.security import get_current_user, get_verified_token
from app.db.session import get_db
from app.models.cube import create_starter_cube
from app.models.user import User
from app.schemas.auth import TwoFactorVerifyRequest
from app.schemas.user import UserRegister, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_LIMIT_PER_IP, key_func=get_remote_address)
@limiter.limit(REGISTER_LIMIT_PER_TOKEN, key_func=get_auth_token_key)
def register(
    request: Request,
    payload: UserRegister,
    decoded_token: dict = Depends(get_verified_token),
    db: Session = Depends(get_db),
    x_device_id: str | None = Header(None, alias="X-Device-Id"),
):
    firebase_uid = decoded_token.get("uid")
    email = decoded_token.get("email")
    if not firebase_uid or not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing uid or email claim")

    if db.query(User).filter(User.firebase_uid == firebase_uid).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "User already registered")

    # Fingerprint básico de device (seção 11) -- gerado e persistido pelo
    # próprio app Flutter, só capturado aqui no cadastro (ver
    # User.device_id). Opcional: clientes que ainda não mandam o header
    # simplesmente não ficam com device_id nenhum.
    user = User(
        firebase_uid=firebase_uid,
        email=email,
        phone=payload.phone,
        pix_key=payload.pix_key,
        device_id=x_device_id,
    )
    db.add(user)
    db.flush()  # popula user.id para o cubo inicial referenciar via FK

    # PRD: usuário ganha um cubo comum ao se registrar.
    db.add(create_starter_cube(user.id))

    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=UserRead)
@limiter.limit(LOGIN_LIMIT_PER_IP, key_func=get_remote_address)
@limiter.limit(LOGIN_LIMIT_PER_TOKEN, key_func=get_auth_token_key)
def login(request: Request, current_user: User = Depends(get_current_user)):
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
