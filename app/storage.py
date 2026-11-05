"""사진 파일을 저장하는 곳.

- .env에 Supabase 설정이 있으면 Supabase Storage(클라우드)에 저장한다.
- 없으면 이 컴퓨터의 uploads/ 폴더에 저장한다(연습 모드).

다른 파일은 save()와 public_url()만 쓰기 때문에, 나중에 저장 방식을 바꿔도 이 파일만 고치면 된다.
"""
from pathlib import Path

from storage3 import SyncStorageClient

from . import config

LOCAL_DIR = Path(__file__).resolve().parent.parent / "uploads"


def make_storage_client(url: str, key: str) -> SyncStorageClient:
    """Supabase Storage에 연결하는 객체를 만든다.

    새 방식 키(sb_secret_...)는 JWT가 아니라서 'apikey' 헤더에만 넣어 보낸다.
    Authorization 헤더에도 넣으면 Storage가 그 키를 JWT로 읽으려다
    'Invalid Compact JWS' 오류를 낸다.
    예전 방식 키(service_role, eyJ...로 시작하는 JWT)는 두 헤더에 모두 넣는다.
    """
    headers = {"apikey": key}
    if not key.startswith("sb_"):
        headers["Authorization"] = f"Bearer {key}"
    return SyncStorageClient(f"{url.rstrip('/')}/storage/v1/", headers)


if config.SUPABASE_URL:
    # 비밀 키는 서버에서만 쓴다. 브라우저로 보내는 화면에는 절대 넣지 않는다.
    client = make_storage_client(config.SUPABASE_URL, config.SUPABASE_SECRET_KEY)
    bucket = client.from_(config.STORAGE_BUCKET)
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


def load(path: str) -> bytes:
    """저장해 둔 사진을 다시 읽어 온다. (나중에 AI 벡터를 다시 만들 때 쓴다)"""
    if bucket is not None:
        return bucket.download(path)
    return (LOCAL_DIR / path).read_bytes()


def delete(paths: list[str]) -> None:
    """사진 파일들을 지운다. (관리자가 글을 지울 때)"""
    if bucket is not None:
        bucket.remove(paths)
    else:
        for path in paths:
            (LOCAL_DIR / path).unlink(missing_ok=True)


def public_url(path: str) -> str:
    """화면에서 <img src="...">에 넣을 사진 주소를 만든다."""
    if bucket is not None:
        return bucket.get_public_url(path)
    return f"/uploads/{path}"
