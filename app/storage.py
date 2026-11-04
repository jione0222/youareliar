"""사진 파일을 저장하는 곳.

- .env에 Supabase 설정이 있으면 Supabase Storage(클라우드)에 저장한다.
- 없으면 이 컴퓨터의 uploads/ 폴더에 저장한다(연습 모드).

다른 파일은 save()와 public_url()만 쓰기 때문에, 나중에 저장 방식을 바꿔도 이 파일만 고치면 된다.
"""
from pathlib import Path

from . import config

LOCAL_DIR = Path(__file__).resolve().parent.parent / "uploads"

if config.SUPABASE_URL:
    from supabase import create_client

    # 비밀 키(secret key)는 서버에서만 쓴다. 브라우저로 보내는 화면에는 절대 넣지 않는다.
    client = create_client(config.SUPABASE_URL, config.SUPABASE_SECRET_KEY)
    bucket = client.storage.from_(config.STORAGE_BUCKET)
else:
    client = None
    bucket = None


def using_supabase() -> bool:
    return bucket is not None


def save(path: str, data: bytes, content_type: str = "image/jpeg") -> None:
    """사진을 path 위치에 저장한다. 예: path = "items/3f2a....jpg" """
    if bucket is not None:
        # 파일 이름이 매번 새로 만들어지므로(바뀌지 않으므로) 브라우저가 1년 동안 캐시해도 된다.
        bucket.upload(path, data, {"content-type": content_type, "cache-control": "31536000"})
    else:
        file = LOCAL_DIR / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)


def public_url(path: str) -> str:
    """화면에서 <img src="...">에 넣을 사진 주소를 만든다."""
    if bucket is not None:
        return bucket.get_public_url(path)
    return f"/uploads/{path}"
