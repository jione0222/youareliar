"""데이터베이스(Postgres)와 이야기하는 곳.

SQL 문장은 모두 이 파일에 모아 둔다. 다른 파일은 여기 있는 함수만 부른다.
"""
from datetime import date

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import config

# 연결 풀: DB 연결을 미리 몇 개 만들어 두고 돌려 쓴다(요청마다 새로 연결하면 느리다).
pool = ConnectionPool(
    config.DATABASE_URL,
    min_size=1,
    max_size=5,
    open=False,  # 서버가 시작될 때 main.py에서 연다
    # 오래 안 쓴 연결은 Supabase나 인터넷 공유기가 중간에 끊어 버리기도 한다.
    # 그래서 연결을 꺼내 줄 때마다 살아 있는지 확인하고, 끊겼으면 버리고 새로 연결한다.
    check=ConnectionPool.check_connection,
    kwargs={
        "row_factory": dict_row,
        # Supabase 연결 중계기(pooler)와 충돌하지 않게 하는 설정
        "prepare_threshold": None,
        # 10초 안에 연결되지 않으면 포기하고 다시 시도한다(길이 막혔을 때 몇 분씩 기다리지 않게).
        "connect_timeout": 10,
        # 쉬는 동안에도 30초마다 '살아 있어요' 신호를 보내서 연결이 덜 끊기게 한다.
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    },
)


def check_connection() -> str | None:
    """DB에 실제로 한 번 연결해 본다. 되면 None, 안 되면 오류 내용을 돌려준다(서버를 켤 때 확인용)."""
    try:
        with psycopg.connect(config.DATABASE_URL, connect_timeout=10) as conn:
            conn.execute("select 1")
    except psycopg.Error as error:
        return str(error).strip() or type(error).__name__
    return None


def add_item(
    photo_path: str,
    thumb_path: str,
    storage_place: str,
    found_place: str | None,
    found_date: date | None,
    memo: str | None,
    user_id: int | None = None,
) -> int:
    """습득물 하나를 저장하고, 새로 붙은 번호(id)를 돌려준다. user_id: 로그인한 등록자(없으면 None)."""
    with pool.connection() as conn:
        row = conn.execute(
            """
            insert into items (photo_path, thumb_path, storage_place, found_place, found_date, memo, user_id)
            values (%s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (photo_path, thumb_path, storage_place, found_place, found_date, memo, user_id),
        ).fetchone()
    return row["id"]


def list_items(limit: int = 60) -> list[dict]:
    """최근에 등록된 습득물부터 보여 준다. 관리자가 숨긴 글은 뺀다."""
    with pool.connection() as conn:
        return conn.execute(
            """
            select id, created_at, thumb_path, storage_place, found_place, found_date, status,
                   ai_info, privacy_reviewed
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
                   i.found_date, i.status, i.ai_info, i.privacy_reviewed,
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


# ---------- B 단계: Claude가 쓴 설명 ----------


def save_description(item_id: int, info: dict, model: str) -> None:
    """Claude가 정리한 결과를 저장한다. info는 ItemDescription을 dict로 바꾼 것."""
    with pool.connection() as conn:
        conn.execute(
            """
            update items
            set ai_description = %s, ai_info = %s, ai_model = %s, ai_described_at = now()
            where id = %s
            """,
            (info["description"], Jsonb(info), model, item_id),
        )


def items_missing_description(limit: int) -> list[dict]:
    """아직 Claude 설명이 없는 물건들 (오래된 것부터)."""
    with pool.connection() as conn:
        return conn.execute(
            """
            select id, photo_path, memo
            from items
            where ai_info is null and not hidden
            order by id
            limit %s
            """,
            (limit,),
        ).fetchall()


# ---------- 관리자 기능 ----------

# 관리자 목록 화면의 보기(탭)별 조건
ADMIN_VIEWS = {
    "all": "true",
    "hidden": "hidden",
    "privacy": "(ai_info->>'has_person_face' = 'true' or ai_info->>'has_personal_info' = 'true')"
               " and not privacy_reviewed",
    "returned": "status = 'returned'",
}


def admin_list_items(view: str, limit: int = 200) -> list[dict]:
    """관리자용 목록. 숨긴 글까지 모두 보여 준다."""
    condition = ADMIN_VIEWS[view]  # 정해 둔 조건만 쓴다(사용자 입력을 SQL에 직접 넣지 않는다)
    with pool.connection() as conn:
        return conn.execute(
            f"""
            select id, created_at, thumb_path, storage_place, found_place, found_date, memo,
                   status, hidden, ai_info, privacy_reviewed
            from items
            where {condition}
            order by created_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()


def set_status(item_id: int, status: str) -> None:
    with pool.connection() as conn:
        conn.execute("update items set status = %s where id = %s", (status, item_id))


def set_hidden(item_id: int, hidden: bool) -> None:
    with pool.connection() as conn:
        conn.execute("update items set hidden = %s where id = %s", (hidden, item_id))


def set_privacy_reviewed(item_id: int, reviewed: bool) -> None:
    with pool.connection() as conn:
        conn.execute("update items set privacy_reviewed = %s where id = %s", (reviewed, item_id))


def delete_item(item_id: int) -> dict | None:
    """물건을 지우고, 지운 물건의 사진 경로를 돌려준다(사진 파일도 지워야 하므로).
    벡터(item_vectors)는 표를 만들 때 정해 둔 규칙(on delete cascade) 덕분에 함께 지워진다."""
    with pool.connection() as conn:
        return conn.execute(
            "delete from items where id = %s returning photo_path, thumb_path", (item_id,)
        ).fetchone()


def admin_counts() -> dict:
    """관리자 화면의 탭에 보여 줄 개수."""
    with pool.connection() as conn:
        return conn.execute(
            f"""
            select count(*) as all,
                   count(*) filter (where {ADMIN_VIEWS["privacy"]}) as privacy,
                   count(*) filter (where hidden) as hidden,
                   count(*) filter (where status = 'returned') as returned
            from items
            """
        ).fetchone()


# ---------- B 검색 ----------


def items_missing_description_vector(model: str) -> list[dict]:
    """Claude 설명은 있는데 설명 벡터가 아직 없는 물건들."""
    with pool.connection() as conn:
        return conn.execute(
            """
            select i.id, i.ai_info, i.memo
            from items i
            where i.ai_info is not null
              and not exists (
                select 1 from item_vectors v
                where v.item_id = i.id and v.model = %s and v.kind = 'description'
              )
            order by i.id
            """,
            (model,),
        ).fetchall()


def count_described() -> int:
    with pool.connection() as conn:
        return conn.execute("select count(*) as n from items where ai_info is not null").fetchone()["n"]


def keyword_rows() -> list[dict]:
    """키워드 검색에 쓸 글 재료 (공개된 물건만)."""
    with pool.connection() as conn:
        return conn.execute(
            "select id, ai_info, memo, found_place, storage_place from items where not hidden"
        ).fetchall()


def items_by_ids(ids: list[int]) -> dict[int, dict]:
    """번호 목록으로 카드에 보여 줄 정보를 한꺼번에 가져온다. {번호: 정보}"""
    if not ids:
        return {}
    with pool.connection() as conn:
        rows = conn.execute(
            """
            select id, created_at, thumb_path, storage_place, found_place, found_date, status,
                   ai_info, privacy_reviewed
            from items
            where id = any(%s) and not hidden
            """,
            (ids,),
        ).fetchall()
    return {row["id"]: row for row in rows}


# ---------- 회원과 로그인 상태 ----------


def create_user(username: str, password_hash: str, nickname: str) -> int | None:
    """회원을 만든다. 같은 아이디가 이미 있으면 None을 돌려준다."""
    with pool.connection() as conn:
        row = conn.execute(
            """
            insert into users (username, password_hash, nickname)
            values (%s, %s, %s)
            on conflict (username) do nothing
            returning id
            """,
            (username, password_hash, nickname),
        ).fetchone()
    return row["id"] if row else None


def get_user_by_username(username: str) -> dict | None:
    with pool.connection() as conn:
        return conn.execute(
            "select id, username, password_hash, nickname from users where username = %s", (username,)
        ).fetchone()


def create_session(token_hash: str, user_id: int, expires_at) -> None:
    with pool.connection() as conn:
        conn.execute("delete from sessions where expires_at < now()")  # 기간이 끝난 로그인 정리
        conn.execute(
            "insert into sessions (token_hash, user_id, expires_at) values (%s, %s, %s)",
            (token_hash, user_id, expires_at),
        )


def delete_session(token_hash: str) -> None:
    with pool.connection() as conn:
        conn.execute("delete from sessions where token_hash = %s", (token_hash,))


def get_user_by_session(token_hash: str) -> dict | None:
    """로그인 표시(토큰)의 해시로 회원을 찾는다. 기간이 끝났으면 None."""
    with pool.connection() as conn:
        return conn.execute(
            """
            select u.id, u.username, u.nickname
            from sessions s join users u on u.id = s.user_id
            where s.token_hash = %s and s.expires_at > now()
            """,
            (token_hash,),
        ).fetchone()


def items_for_rerank(ids: list[int]) -> list[dict]:
    """재순위에 쓸 후보 정보 (공개된 물건만, 받은 번호 순서대로)."""
    if not ids:
        return []
    with pool.connection() as conn:
        rows = conn.execute(
            """
            select id, ai_info, memo, found_place, found_date, storage_place
            from items
            where id = any(%s) and not hidden
            """,
            (ids,),
        ).fetchall()
    by_id = {row["id"]: row for row in rows}
    return [by_id[i] for i in ids if i in by_id]

