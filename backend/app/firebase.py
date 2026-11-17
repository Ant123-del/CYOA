import firebase_admin
from firebase_admin import credentials, firestore

from .config import get_settings

_db = None


def init_firebase() -> None:
    if not firebase_admin._apps:
        key = get_settings().service_account_path
        if key.exists():
            firebase_admin.initialize_app(credentials.Certificate(str(key)))
        else:  # Cloud Functions: use the runtime service account
            firebase_admin.initialize_app()


def db():
    global _db
    if _db is None:
        init_firebase()
        _db = firestore.client()
    return _db


def user_ref(uid: str):
    return db().collection("users").document(uid)
