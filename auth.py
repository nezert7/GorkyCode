import os
import hmac
import json
import time
import base64
import hashlib
import secrets
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

load_dotenv(override=True)

SECRET_KEY = (os.getenv("VORONA_SECRET_KEY") or "vorona-super-secret-key-2026-change-me").encode("utf-8")
TOKEN_EXPIRE_SECONDS = 30 * 24 * 3600  # 30 дней

security_scheme = HTTPBearer(auto_error=False)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Хеширует пароль алгоритмом PBKDF2-HMAC-SHA256 со случайной солью."""
    salt_str = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_str.encode("utf-8"),
        120_000
    )
    return f"{salt_str}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Проверяет пароль с защитой от атак по времени."""
    if not stored_hash or "$" not in stored_hash:
        return False
    salt_str, _ = stored_hash.split("$", 1)
    candidate_hash = hash_password(password, salt=salt_str)
    return hmac.compare_digest(candidate_hash, stored_hash)


def create_access_token(user_id: int, username: str) -> str:
    """Создаёт подписанный HMAC-SHA256 токен сессии."""
    payload = {
        "sub": int(user_id),
        "username": username,
        "exp": int(time.time()) + TOKEN_EXPIRE_SECONDS
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(SECRET_KEY, payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)
    return f"{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Проверяет подпись и срок действия токена."""
    try:
        if not token or "." not in token:
            return None
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(SECRET_KEY, payload_b64.encode("ascii"), hashlib.sha256).digest()
        expected_sig_b64 = _b64url_encode(expected_sig)

        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None

        return {
            "id": int(payload["sub"]),
            "username": str(payload["username"])
        }
    except Exception:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    token_query: Optional[str] = Query(None, alias="token")
) -> Dict[str, Any]:
    """FastAPI-зависимость: возвращает авторизованного пользователя или ошибку 401."""
    raw_token = None
    if credentials and credentials.credentials:
        raw_token = credentials.credentials
    elif token_query:
        raw_token = token_query

    user_data = decode_access_token(raw_token or "")
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима авторизация в аккаунт Вороны"
        )
    return user_data