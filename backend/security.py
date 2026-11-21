import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from database import closing, get_connection, utc_now


PASSWORD_ITERATIONS = 310_000
TOKEN_LIFETIME_SECONDS = 8 * 60 * 60
DEMO_MODE = os.environ.get("CIVICPREDICT_DEMO_MODE", "true").strip().lower() not in {
    "0", "false", "no", "off"
}
DEMO_USERNAME = "__demo_operator__"
bearer_scheme = HTTPBearer(auto_error=False)


def _token_secret():
    secret = os.environ.get("CIVICPREDICT_SECRET_KEY", "")
    if len(secret.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=503,
            detail=(
                "Authentication is not configured. Set "
                "CIVICPREDICT_SECRET_KEY to a secret of at least 32 bytes."
            ),
        )
    return secret.encode("utf-8")


def hash_password(password, salt=None, iterations=PASSWORD_ITERATIONS):
    salt_bytes = salt or secrets.token_bytes(16)
    if isinstance(salt_bytes, str):
        salt_bytes = bytes.fromhex(salt_bytes)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_bytes, iterations
    )
    return salt_bytes.hex(), password_hash.hex(), iterations


def verify_password(password, salt, expected_hash, iterations):
    _, actual_hash, _ = hash_password(password, salt, iterations)
    return hmac.compare_digest(actual_hash, expected_hash)


def _get_demo_user():
    with closing(get_connection()) as connection:
        user = connection.execute(
            "SELECT user_id, username, display_name, department_id, is_active FROM users WHERE username = ?",
            (DEMO_USERNAME,),
        ).fetchone()
        if user is None:
            salt, password_hash, iterations = hash_password(secrets.token_urlsafe(48))
            try:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO users (
                            username, display_name, password_hash, password_salt,
                            password_iterations, role, created_at
                        )
                        VALUES (?, 'Demo Operator', ?, ?, ?, 'citizen', ?)
                        """,
                        (
                            DEMO_USERNAME,
                            password_hash,
                            salt,
                            iterations,
                            utc_now(),
                        ),
                    )
            except sqlite3.IntegrityError:
                pass
            user = connection.execute(
                """
                SELECT user_id, username, display_name, department_id, is_active
                FROM users WHERE username = ?
                """,
                (DEMO_USERNAME,),
            ).fetchone()
    if user is None:
        raise RuntimeError("Unable to initialize the CivicPredict demo operator.")
    return {**dict(user), "role": "administrator"}


def _encode_part(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def create_access_token(user_id):
    secret = _token_secret()
    payload = _encode_part(
        json.dumps(
            {"sub": user_id, "exp": int(time.time()) + TOKEN_LIFETIME_SECONDS},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = _encode_part(
        hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{payload}.{signature}"


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if DEMO_MODE:
        return _get_demo_user()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")
    secret = _token_secret()
    try:
        payload_part, signature_part = credentials.credentials.split(".", 1)
        expected_signature = _encode_part(
            hmac.new(secret, payload_part.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature_part, expected_signature):
            raise ValueError("Invalid token signature.")
        payload_bytes = base64.urlsafe_b64decode(
            payload_part + "=" * (-len(payload_part) % 4)
        )
        payload = json.loads(payload_bytes.decode("utf-8"))
        user_id = int(payload["sub"])
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("Expired token.")
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=401, detail="Invalid or expired access token."
        ) from error

    with closing(get_connection()) as connection:
        user = connection.execute(
            """
            SELECT user_id, username, display_name, role, department_id, is_active
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User account is inactive.")
    return dict(user)


def require_roles(*roles):
    def role_dependency(user=Depends(get_current_user)):
        if DEMO_MODE:
            if roles == ("citizen",):
                return {**user, "role": "citizen"}
            return user
        if user["role"] not in roles:
            raise HTTPException(
                status_code=403,
                detail="Your account is not authorized for this operation.",
            )
        return user

    return role_dependency

