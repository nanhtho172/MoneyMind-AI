import hashlib
import hmac
import secrets

from itsdangerous import BadData, URLSafeTimedSerializer

from backend.app.core.config import Settings


def _derive_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${_derive_password(password, salt).hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, salt, digest = password_hash.split("$")
        if scheme != "scrypt":
            return False
        return hmac.compare_digest(
            _derive_password(password, bytes.fromhex(salt)), bytes.fromhex(digest)
        )
    except ValueError:
        return False


def issue_access_token(user_id: int, settings: Settings) -> str:
    return _token_serializer(settings).dumps(user_id)


def _token_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        settings.auth_secret_key.get_secret_value(),
        salt="moneymind-ai.access-token.v1",
        signer_kwargs={"digest_method": hashlib.sha256},
    )


def read_access_token(token: str, settings: Settings) -> int:
    user_id = _token_serializer(settings).loads(
        token, max_age=settings.access_token_expire_minutes * 60
    )
    if type(user_id) is not int or not 0 < user_id <= 2**63 - 1:
        raise BadData("Invalid token subject")
    return user_id
