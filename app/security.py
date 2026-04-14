import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _app_secret() -> str:
    return os.getenv("MAILAI_APP_SECRET", "change-me-in-production")


def password_hash(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd_context.verify(raw, hashed)


def create_access_token(user_id: int, email: str, minutes: int = 60 * 24 * 7) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": str(user_id), "email": email, "exp": exp}
    return jwt.encode(payload, _app_secret(), algorithm="HS256")


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _app_secret(), algorithms=["HS256"])
    except JWTError:
        return None


def _fernet_key() -> bytes:
    digest = hashlib.sha256(_app_secret().encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(raw: str) -> str:
    return Fernet(_fernet_key()).encrypt(raw.encode("utf-8")).decode("utf-8")


def decrypt_secret(enc: str) -> str:
    return Fernet(_fernet_key()).decrypt(enc.encode("utf-8")).decode("utf-8")

