import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

from app.core.config import settings

_firebase_app: firebase_admin.App | None = None


class InvalidFirebaseTokenError(Exception):
    pass


def _get_firebase_app() -> firebase_admin.App:
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app
    if firebase_admin._apps:
        _firebase_app = firebase_admin.get_app()
        return _firebase_app
    cred = (
        credentials.Certificate(settings.FIREBASE_CREDENTIALS_FILE)
        if settings.FIREBASE_CREDENTIALS_FILE
        else credentials.ApplicationDefault()
    )
    _firebase_app = firebase_admin.initialize_app(cred)
    return _firebase_app


def verify_firebase_token(id_token: str) -> dict:
    try:
        return firebase_auth.verify_id_token(id_token, app=_get_firebase_app())
    except Exception as exc:
        raise InvalidFirebaseTokenError(str(exc)) from exc
