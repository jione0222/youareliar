"""회원 기능의 바탕: 비밀번호를 안전하게 저장하고, 로그인 상태(세션)를 확인한다.

비밀번호 저장
- 비밀번호를 그대로 저장하면 DB가 유출됐을 때 모두 들킨다.
- 그래서 scrypt라는 '일부러 느리고 되돌릴 수 없는' 계산으로 바꾼 값(해시)만 저장한다.
- 같은 비밀번호라도 사람마다 무작위 소금(salt)을 섞어서 해시가 달라지게 한다.
- 로그인할 때는 입력한 비밀번호를 같은 방법으로 바꿔서 저장된 값과 비교한다.

로그인 상태
- 로그인하면 아무도 맞힐 수 없는 무작위 글자(토큰)를 만들어 브라우저 쿠키에 넣는다.
- DB에는 토큰의 해시만 적어 두고, 요청이 올 때마다 쿠키의 토큰을 확인한다.
"""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request

from . import db

SESSION_COOKIE = "session"
_NOT_LOADED = object()
SESSION_DAYS = 30  # 한 번 로그인하면 30일 동안 유지

# scrypt 설정: 숫자가 클수록 느리고 안전하다(로그인 한 번에 0.1초 안쪽)
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(user_id: int) -> str:
    """로그인 상태를 만들고, 쿠키에 넣을 토큰을 돌려준다."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    db.create_session(_token_hash(token), user_id, expires_at)
    return token


def end_session(token: str) -> None:
    db.delete_session(_token_hash(token))


def current_user(request: Request) -> dict | None:
    """지금 요청을 보낸 사람이 로그인했으면 회원 정보를, 아니면 None을 돌려준다."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    # 같은 요청 안에서 여러 번 불려도 DB는 한 번만 묻는다.
    cached = getattr(request.state, "current_user", _NOT_LOADED)
    if cached is _NOT_LOADED:
        cached = db.get_user_by_session(_token_hash(token))
        request.state.current_user = cached
    return cached
