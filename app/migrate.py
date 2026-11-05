"""처음 설정할 때(그리고 DB 구조가 바뀔 때마다) 실행하는 준비 스크립트.

1. db/migrations 폴더의 SQL 파일을 이름 순서대로 DB에 적용한다.
   이미 적용한 파일은 schema_migrations 표에 기록해 두고 건너뛴다.
   (실제 서비스들도 이런 '마이그레이션' 방식으로 DB 구조를 바꾼다.)
2. Supabase를 쓰는 경우, 사진을 담을 저장 공간(버킷)이 없으면 만든다.

실행 방법:  python -m app.migrate
"""
from pathlib import Path

import psycopg
from storage3.exceptions import StorageApiError

from . import config, storage

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"


def apply_sql_migrations() -> None:
    with psycopg.connect(config.DATABASE_URL, prepare_threshold=None) as conn:
        conn.execute(
            """
            create table if not exists schema_migrations (
                name       text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        conn.execute("alter table schema_migrations enable row level security")
        conn.commit()

        done = {row[0] for row in conn.execute("select name from schema_migrations")}
        for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if file.name in done:
                print(f"  건너뜀(이미 적용됨): {file.name}")
                continue
            # 파일 하나를 통째로 한 번에 적용한다. 중간에 오류가 나면 그 파일 전체가 취소된다.
            conn.execute(file.read_text(encoding="utf-8"))
            conn.execute("insert into schema_migrations (name) values (%s)", (file.name,))
            conn.commit()
            print(f"  적용함: {file.name}")


def ensure_bucket() -> None:
    if not storage.using_supabase():
        print("  Supabase 설정이 없어 연습 모드로 동작합니다(사진은 uploads 폴더에 저장).")
        return
    try:
        existing = {b.id for b in storage.client.list_buckets()}
        if config.STORAGE_BUCKET in existing:
            print(f"  사진 저장 공간 '{config.STORAGE_BUCKET}'이 이미 있습니다.")
            return
        storage.client.create_bucket(
            config.STORAGE_BUCKET,
            options={
                "public": True,  # 목록에서 사진을 보여 줘야 하므로 공개
                "allowed_mime_types": ["image/jpeg"],  # 서버가 JPEG로 바꿔서만 올린다
                "file_size_limit": 5 * 1024 * 1024,  # 5MB
            },
        )
    except StorageApiError as error:
        raise SystemExit(
            f"\n[사진 저장소 오류] {error}\n"
            "SUPABASE_SECRET_KEY를 Supabase의 Project Settings → API Keys에서 다시 복사해 넣어 보세요.\n"
            "그래도 같은 오류가 나면 이 메시지를 보내 주세요(키는 지우고).\n"
        )
    print(f"  사진 저장 공간 '{config.STORAGE_BUCKET}'을 만들었습니다.")


if __name__ == "__main__":
    print("1) DB 표 만들기")
    apply_sql_migrations()
    print("2) 사진 저장 공간 확인")
    ensure_bucket()
    print("준비 완료!")
