"""데이터베이스(Postgres)와 이야기하는 곳.

SQL 문장은 모두 이 파일에 모아 둔다. 다른 파일은 여기 있는 함수만 부른다.
"""
from datetime import date

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

# 연결 풀: DB 연결을 미리 몇 개 만들어 두고 돌려 쓴다(요청마다 새로 연결하면 느리다).
# prepare_threshold=None 은 Supabase 연결 중계기(pooler)와 충돌하지 않게 하는 설정이다.
pool = ConnectionPool(
    config.DATABASE_URL,
    min_size=1,
    max_size=5,
    open=False,  # 서버가 시작될 때 main.py에서 연다
    kwargs={"row_factory": dict_row, "prepare_threshold": None},
)


def add_item(
    photo_path: str,
    thumb_path: str,
    storage_place: str,
    found_place: str | None,
    found_date: date | None,
    memo: str | None,
) -> int:
    """습득물 하나를 저장하고, 새로 붙은 번호(id)를 돌려준다."""
    with pool.connection() as conn:
        row = conn.execute(
            """
            insert into items (photo_path, thumb_path, storage_place, found_place, found_date, memo)
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (photo_path, thumb_path, storage_place, found_place, found_date, memo),
        ).fetchone()
    return row["id"]


def list_items(limit: int = 60) -> list[dict]:
    """최근에 등록된 습득물부터 보여 준다. 관리자가 숨긴 글은 뺀다."""
    with pool.connection() as conn:
        return conn.execute(
            """
            select id, created_at, thumb_path, storage_place, found_place, found_date, status
            from items
            where not hidden
            order by created_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()


def get_item(item_id: int) -> dict | None:
    """번호로 습득물 하나를 찾는다. 없으면 None."""
    with pool.connection() as conn:
        return conn.execute("select * from items where id = %s", (item_id,)).fetchone()
