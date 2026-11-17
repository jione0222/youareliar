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

from . import config, db, storage

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"
# 서버가 여러 대 동시에 켜져도 한 대씩만 적용하게 거는 '자물쇠' 번호(아무 숫자나 정해 두면 된다)
MIGRATION_LOCK = 20261117
# 자물쇠를 기다리는 최대 시간
LOCK_WAIT = "30s"


def _pending(conn) -> list[Path]:
    """아직 적용하지 않은 SQL 파일 목록(이름 순서)."""
    if conn.execute("select to_regclass('schema_migrations')").fetchone()[0] is None:
        done = set()  # 처음 설정하는 DB
    else:
        done = {row[0] for row in conn.execute("select name from schema_migrations")}
    return [file for file in sorted(MIGRATIONS_DIR.glob("*.sql")) if file.name not in done]


def apply_sql_migrations(say=print) -> list[str]:
    """아직 적용하지 않은 SQL 파일을 순서대로 적용하고, 적용한 파일 이름을 돌려준다.
    서버가 켜질 때(main.py)도 이 함수를 불러서, 새 코드를 올리면 DB 구조도 알아서 바뀐다."""
    try:
        conn = psycopg.connect(config.DATABASE_URL, prepare_threshold=None, connect_timeout=10)
    except psycopg.OperationalError as error:
        message = str(error).strip()
        raise SystemExit(f"\n[DB 연결 실패] {db.connection_hint(message)}\n  오류 내용: {message.splitlines()[0]}\n")
    applied = []
    with conn:
        # 바꿀 것이 없으면 자물쇠 없이 바로 끝낸다(서버가 켜질 때 대부분 이 경우).
        if not _pending(conn):
            say("  새로 적용할 파일이 없어요(모두 적용됨).")
            return applied
        # 자물쇠를 기다리는 시간을 정해 둔다. 자물쇠가 어딘가에 남아 있어도 서버가 계속 멈춰 있지 않게.
        conn.execute("select set_config('lock_timeout', %s, true)", (LOCK_WAIT,))
        try:
            conn.execute("select pg_advisory_lock(%s)", (MIGRATION_LOCK,))
        except psycopg.errors.LockNotAvailable:
            raise SystemExit(
                f"\n[DB 구조 바꾸기 못 함] 다른 서버가 DB 구조를 바꾸는 중이라 {LOCK_WAIT} 기다렸지만 끝나지 않았어요.\n"
                "  잠시 뒤 서버를 다시 켜거나 python -m app.migrate를 다시 실행하세요.\n"
            )
        conn.commit()
        try:
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
            # 자물쇠를 건 뒤에 다시 확인한다(기다리는 사이 다른 서버가 적용했을 수 있다).
            for file in _pending(conn):
                # 파일 하나를 통째로 한 번에 적용한다. 중간에 오류가 나면 그 파일 전체가 취소된다.
                conn.execute(file.read_text(encoding="utf-8"))
                conn.execute("insert into schema_migrations (name) values (%s)", (file.name,))
                conn.commit()
                say(f"  적용함: {file.name}")
                applied.append(file.name)
        finally:
            # 자물쇠는 꼭 직접 푼다. Supabase 연결 중계기(pooler)는 우리가 연결을 끊어도 DB 쪽 연결을
            # 다음 손님에게 다시 쓸 수 있어서, 그냥 두면 자물쇠가 남아 다음에 켜지는 서버가 기다리게 된다.
            conn.rollback()  # 오류로 멈춘 작업이 있으면 먼저 취소하고
            conn.execute("select pg_advisory_unlock(%s)", (MIGRATION_LOCK,))
            conn.commit()
    return applied


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
