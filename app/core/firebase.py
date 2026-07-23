import json

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

from app.core.config import settings

_firebase_app: firebase_admin.App | None = None


class InvalidFirebaseTokenError(Exception):
    pass


def _build_credentials() -> credentials.Base:
    # FIREBASE_CREDENTIALS_JSON tem prioridade: o JSON da service account
    # como texto, parseado em memória -- não precisa de um arquivo montado
    # no disco (útil em provedores como o Render sem Secret Files).
    if settings.FIREBASE_CREDENTIALS_JSON:
        return credentials.Certificate(json.loads(settings.FIREBASE_CREDENTIALS_JSON))
    if settings.FIREBASE_CREDENTIALS_FILE:
        return credentials.Certificate(settings.FIREBASE_CREDENTIALS_FILE)
    return credentials.ApplicationDefault()


def _get_firebase_app() -> firebase_admin.App:
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app
    if firebase_admin._apps:
        _firebase_app = firebase_admin.get_app()
        return _firebase_app
    _firebase_app = firebase_admin.initialize_app(_build_credentials())
    return _firebase_app


def verify_firebase_token(id_token: str) -> dict:
    try:
        return firebase_auth.verify_id_token(id_token, app=_get_firebase_app())
    except Exception as exc:
        raise InvalidFirebaseTokenError(str(exc)) from exc
