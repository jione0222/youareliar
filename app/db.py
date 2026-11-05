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


# ---------- A 검색: 벡터 저장과 검색 ----------


def to_pg_vector(vector) -> str:
    """파이썬 숫자 목록을 Postgres가 읽을 수 있는 '[0.1,0.2,...]' 글자로 바꾼다."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


def save_vector(item_id: int, model: str, kind: str, vector) -> None:
    """물건 하나의 벡터를 저장한다. 같은 모델·종류의 벡터가 이미 있으면 새 것으로 바꾼다."""
    with pool.connection() as conn:
        conn.execute(
            """
            insert into item_vectors (item_id, model, kind, embedding)
            values (%s, %s, %s, %s::vector)
            on conflict (item_id, model, kind)
            do update set embedding = excluded.embedding, created_at = now()
            """,
            (item_id, model, kind, to_pg_vector(vector)),
        )


def items_missing_vector(model: str, kind: str) -> list[dict]:
    """아직 벡터가 없는 물건들. (AI 모델이 준비되기 전에 등록됐거나, 모델을 바꿨을 때)"""
    with pool.connection() as conn:
        return conn.execute(
            """
            select i.id, i.photo_path
            from items i
            where not exists (
                select 1 from item_vectors v
                where v.item_id = i.id and v.model = %s and v.kind = %s
            )
            order by i.id
            """,
            (model, kind),
        ).fetchall()


def search_by_vector(vector, model: str, kind: str, limit: int = 20) -> list[dict]:
    """검색 문장의 벡터와 가장 가까운 물건부터 돌려준다.

    <=> 는 pgvector의 '코사인 거리' 계산 기호다. 거리가 작을수록 비슷하다.
    (코사인 유사도 = 1 - 코사인 거리)
    """
    with pool.connection() as conn:
        return conn.execute(
            """
            select i.id, i.created_at, i.thumb_path, i.storage_place, i.found_place,
                   i.found_date, i.status,
                   1 - (v.embedding <=> q.vec) as similarity
            from item_vectors v
            join items i on i.id = v.item_id
            cross join (select %s::vector as vec) q
            where v.model = %s and v.kind = %s and not i.hidden
            order by v.embedding <=> q.vec
            limit %s
            """,
            (to_pg_vector(vector), model, kind, limit),
        ).fetchall()
