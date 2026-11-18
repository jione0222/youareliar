"""데이터베이스(Postgres)와 이야기하는 곳.

SQL 문장은 모두 이 파일에 모아 둔다. 다른 파일은 여기 있는 함수만 부른다.
"""
from datetime import date

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import categories, config

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


# DB에 연결하지 못했을 때: 오류 글자에 들어 있는 말 → 고치는 방법 (자주 나오는 것만)
CONNECTION_HINTS = [
    (("password authentication failed",), "DATABASE_URL의 비밀번호가 틀렸어요. 대괄호 [ ]까지 지우고 비밀번호만 넣었는지 확인하세요."),
    (("Tenant or user not found",), "DATABASE_URL의 사용자 이름이 틀렸어요. Supabase의 Connect → Session pooler 주소를 다시 복사하세요."),
    (("failed to resolve host", "could not translate host name", "getaddrinfo failed"), "DATABASE_URL의 주소(@ 뒤쪽)가 틀렸거나 인터넷이 끊겼어요."),
    (("Network is unreachable",), "DB 주소로 가는 길이 없어요. Supabase의 Direct connection 주소 대신 Session pooler 주소를 쓰세요."),
    (("timeout expired",), "10초 안에 연결되지 않았어요. 인터넷이 느리거나, 이 서버에서 DB 포트(5432)로 나가는 연결이 막혀 있어요. (Hugging Face Spaces는 80·443·8080 포트만 열려 있어서 안 돼요.)"),
    (("Connection refused",), "DB가 꺼져 있거나 주소·포트가 틀렸어요. 이 컴퓨터의 Postgres를 쓴다면 켜져 있는지 확인하세요."),
]


def connection_hint(error: str) -> str:
    """DB 연결 오류 글자를 보고 고치는 방법을 한국어로 돌려준다."""
    return next(
        (hint for words, hint in CONNECTION_HINTS if any(word in error for word in words)),
        "DATABASE_URL 값을 다시 확인하세요.",
    )


def check_connection() -> str | None:
    """DB에 실제로 한 번 연결해 본다. 되면 None, 안 되면 오류 내용을 돌려준다(서버를 켤 때 확인용)."""
    try:
        with psycopg.connect(config.DATABASE_URL, connect_timeout=10) as conn:
            conn.execute("select 1")
    except psycopg.Error as error:
        return str(error).strip() or type(error).__name__
    return None


# AI(Claude)와 검색에 넘기는 '주운 사람이 쓴 글': 제목과 메모를 합쳐서 memo라는 이름으로 읽는다.
# 예: 제목 '파란 텀블러', 메모 '뚜껑에 스티커' → '파란 텀블러 / 뚜껑에 스티커'
NOTE = "nullif(concat_ws(' / ', title, memo), '') as memo"


def add_item(
    photo_path: str,
    thumb_path: str,
    storage_place: str,
    found_place: str | None,
    found_date: date | None,
    memo: str | None,
    user_id: int | None = None,
    title: str | None = None,
    category: str | None = None,
    finder_name: str | None = None,
    finder_phone: str | None = None,
) -> int:
    """습득물 하나를 저장하고, 새로 붙은 번호(id)를 돌려준다.
    user_id: 로그인한 등록자, category: 등록한 사람이 고른 종류, finder_*: 습득자 연락처 (모두 없으면 None)"""
    with pool.connection() as conn:
        row = conn.execute(
            """
            insert into items (photo_path, thumb_path, storage_place, found_place, found_date, memo, user_id,
                               category, finder_name, finder_phone, title)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (photo_path, thumb_path, storage_place, found_place, found_date, memo, user_id,
             category, finder_name, finder_phone, title),
        ).fetchone()
    return row["id"]


# 목록 정렬 방법: 화면에서 받은 이름 → SQL의 order by (정해 둔 것만 쓴다. 사용자 입력을 SQL에 넣지 않는다)
SORTS = {
    "new": "created_at desc",
    "old": "created_at asc",
    "views": "view_count desc, created_at desc",
}


def list_items(sort: str = "new", category: str | None = None, limit: int = 60) -> list[dict]:
    """습득물 목록. sort: new(최신순) / old(오래된순) / views(조회순), category: 이 종류만 (None이면 전부).
    관리자가 숨긴 글은 뺀다."""
    order = SORTS.get(sort, SORTS["new"])
    with pool.connection() as conn:
        return conn.execute(
            f"""
            select id, created_at, thumb_path, storage_place, found_place, found_date, status,
                   ai_info, privacy_reviewed, category, view_count, title
            from items
            where not hidden and (%s::text is null or category = %s)
            order by {order}
            limit %s
            """,
            (category, category, limit),
        ).fetchall()


def add_view(item_id: int) -> None:
    """상세 화면을 한 번 열 때마다 조회 수를 1 올린다(조회순 정렬에 쓴다)."""
    with pool.connection() as conn:
        conn.execute("update items set view_count = view_count + 1 where id = %s", (item_id,))


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


def search_by_vector(vector, model: str, kind: str, limit: int = 20, category: str | None = None) -> list[dict]:
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
              and (%s::text is null or i.category = %s)
            order by v.embedding <=> q.vec
            limit %s
            """,
            (to_pg_vector(vector), model, kind, category, category, limit),
        ).fetchall()


# ---------- B 단계: Claude가 쓴 설명 ----------


def save_description(item_id: int, info: dict, model: str) -> None:
    """Claude가 정리한 결과를 저장한다. info는 ItemDescription을 dict로 바꾼 것."""
    with pool.connection() as conn:
        conn.execute(
            """
            update items
            set ai_description = %s, ai_info = %s, ai_model = %s, ai_described_at = now(),
                category = coalesce(category, %s)  -- 등록한 사람이 고른 종류가 있으면 그대로 둔다
            where id = %s
            """,
            (info["description"], Jsonb(info), model, categories.clean(info.get("group")), item_id),
        )


def items_missing_description(limit: int) -> list[dict]:
    """아직 Claude 설명이 없는 물건들 (오래된 것부터)."""
    with pool.connection() as conn:
        return conn.execute(
            f"""
            select id, photo_path, {NOTE}
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


# 관리 화면(관리자 화면과 '내가 등록한 물건')에서 보여 줄 칸
MANAGE_COLUMNS = """id, created_at, thumb_path, storage_place, found_place, found_date, memo, title,
                   status, hidden, ai_info, privacy_reviewed, category, view_count,
                   finder_name, finder_phone, claimant_name, claimant_student_id, returned_at, user_id"""


def admin_list_items(view: str, limit: int = 200) -> list[dict]:
    """관리자용 목록. 숨긴 글까지 모두 보여 준다."""
    condition = ADMIN_VIEWS[view]  # 정해 둔 조건만 쓴다(사용자 입력을 SQL에 직접 넣지 않는다)
    with pool.connection() as conn:
        return conn.execute(
            f"""
            select {MANAGE_COLUMNS}
            from items
            where {condition}
            order by created_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()


def set_status(item_id: int, status: str, claimant_name: str | None = None,
               claimant_student_id: str | None = None) -> None:
    """'주인 찾음'(returned)으로 바꾸면 찾아간 사람(이름·학번)과 시각을 함께 적고,
    '보관 중'(stored)으로 되돌리면 그 기록을 지운다."""
    with pool.connection() as conn:
        if status == "returned":
            conn.execute(
                """
                update items set status = 'returned', claimant_name = %s, claimant_student_id = %s,
                                 returned_at = now()
                where id = %s
                """,
                (claimant_name, claimant_student_id, item_id),
            )
        else:
            conn.execute(
                """
                update items set status = %s, claimant_name = null, claimant_student_id = null,
                                 returned_at = null
                where id = %s
                """,
                (status, item_id),
            )


# 등록한 사람용: 찾아간 사람의 이름·학번은 관리자만 보므로 읽지 않고, 기록이 있는지만 알려 준다.
MY_COLUMNS = """id, created_at, thumb_path, storage_place, found_place, found_date, memo, title,
               status, hidden, ai_info, privacy_reviewed, category, view_count,
               finder_name, finder_phone, returned_at, user_id,
               (claimant_name is not null or claimant_student_id is not null) as has_claimant"""


def my_items(user_id: int) -> list[dict]:
    """로그인한 사람이 등록한 물건들 (숨긴 글까지)."""
    with pool.connection() as conn:
        return conn.execute(
            f"""
            select {MY_COLUMNS}
            from items
            where user_id = %s
            order by created_at desc
            """,
            (user_id,),
        ).fetchall()


def item_owner(item_id: int) -> int | None:
    """물건을 등록한 회원 번호 (로그인하지 않고 등록했거나 물건이 없으면 None)."""
    with pool.connection() as conn:
        row = conn.execute("select user_id from items where id = %s", (item_id,)).fetchone()
    return row["user_id"] if row else None


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
            f"""
            select i.id, i.ai_info, {NOTE}
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


def keyword_rows(category: str | None = None) -> list[dict]:
    """키워드 검색에 쓸 글 재료 (공개된 물건만, category가 있으면 그 종류만)."""
    with pool.connection() as conn:
        return conn.execute(
            f"""
            select id, ai_info, {NOTE}, found_place, storage_place from items
            where not hidden and (%s::text is null or category = %s)
            """,
            (category, category),
        ).fetchall()


def items_missing_category() -> list[dict]:
    """종류가 아직 비어 있는 물건들 (짐작해서 채우려고)."""
    with pool.connection() as conn:
        return conn.execute(f"select id, ai_info, {NOTE} from items where category is null").fetchall()


def set_category_if_empty(item_id: int, category: str) -> None:
    with pool.connection() as conn:
        conn.execute("update items set category = %s where id = %s and category is null", (category, item_id))


def items_by_ids(ids: list[int]) -> dict[int, dict]:
    """번호 목록으로 카드에 보여 줄 정보를 한꺼번에 가져온다. {번호: 정보}"""
    if not ids:
        return {}
    with pool.connection() as conn:
        rows = conn.execute(
            """
            select id, created_at, thumb_path, storage_place, found_place, found_date, status,
                   ai_info, privacy_reviewed, category, view_count, title
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
            f"""
            select id, ai_info, {NOTE}, found_place, found_date, storage_place
            from items
            where id = any(%s) and not hidden
            """,
            (ids,),
        ).fetchall()
    by_id = {row["id"]: row for row in rows}
    return [by_id[i] for i in ids if i in by_id]



# ---------- 쪽지함 (회원 ↔ 관리자) ----------


def get_user(user_id: int) -> dict | None:
    with pool.connection() as conn:
        return conn.execute(
            "select id, username, nickname, created_at from users where id = %s", (user_id,)
        ).fetchone()


def item_brief(item_id: int) -> dict | None:
    """쪽지에 붙일 물건의 간단한 정보 (습득자 연락처나 찾아간 사람 기록은 읽지 않는다)."""
    with pool.connection() as conn:
        return conn.execute(
            """
            select id, thumb_path, storage_place, status, hidden, user_id, category, ai_info, privacy_reviewed, title
            from items where id = %s
            """,
            (item_id,),
        ).fetchone()


def manage_items_by_ids(ids: list[int]) -> list[dict]:
    """관리자용: 쪽지에 나온 물건들 (찾아간 사람 기록까지)."""
    if not ids:
        return []
    with pool.connection() as conn:
        return conn.execute(
            f"select {MANAGE_COLUMNS} from items where id = any(%s) order by id", (ids,)
        ).fetchall()


def add_message(user_id: int, body: str, from_admin: bool = False, item_id: int | None = None) -> None:
    with pool.connection() as conn:
        conn.execute(
            "insert into messages (user_id, from_admin, item_id, body) values (%s, %s, %s, %s)",
            (user_id, from_admin, item_id, body),
        )


def thread(user_id: int) -> list[dict]:
    """한 회원과 관리자가 주고받은 쪽지 (오래된 것부터). 붙인 물건의 이름·보관 장소도 같이."""
    with pool.connection() as conn:
        return conn.execute(
            """
            select m.id, m.from_admin, m.item_id, m.body, m.created_at, m.read_at,
                   i.storage_place as item_place, i.hidden as item_hidden,
                   coalesce(i.title, i.ai_info->>'category', i.category) as item_name
            from messages m left join items i on i.id = m.item_id
            where m.user_id = %s
            order by m.id
            """,
            (user_id,),
        ).fetchall()


def mark_read(user_id: int, from_admin: bool) -> None:
    """from_admin=True: 회원이 관리자의 쪽지를 읽음 / False: 관리자가 회원의 쪽지를 읽음."""
    with pool.connection() as conn:
        conn.execute(
            "update messages set read_at = now() where user_id = %s and from_admin = %s and read_at is null",
            (user_id, from_admin),
        )


def unread_for_user(user_id: int) -> int:
    """회원이 아직 안 읽은 관리자 쪽지 수."""
    with pool.connection() as conn:
        return conn.execute(
            "select count(*) as n from messages where user_id = %s and from_admin and read_at is null",
            (user_id,),
        ).fetchone()["n"]


def unread_for_admin() -> int:
    """관리자가 아직 안 읽은 회원 쪽지 수."""
    with pool.connection() as conn:
        return conn.execute(
            "select count(*) as n from messages where not from_admin and read_at is null"
        ).fetchone()["n"]


def sent_today(user_id: int) -> int:
    """회원이 최근 24시간 동안 보낸 쪽지 수 (장난 쪽지 막기)."""
    with pool.connection() as conn:
        return conn.execute(
            """
            select count(*) as n from messages
            where user_id = %s and not from_admin and created_at > now() - interval '24 hours'
            """,
            (user_id,),
        ).fetchone()["n"]


def conversations(limit: int = 200) -> list[dict]:
    """관리자용 대화 목록: 회원마다 마지막 쪽지와 안 읽은 수 (최근 대화부터)."""
    with pool.connection() as conn:
        return conn.execute(
            """
            select u.id, u.username, u.nickname,
                   last.body as last_body, last.from_admin as last_from_admin, last.created_at as last_at,
                   (select count(*) from messages x
                    where x.user_id = u.id and not x.from_admin and x.read_at is null) as unread
            from users u
            join lateral (
                select body, from_admin, created_at from messages m
                where m.user_id = u.id order by m.id desc limit 1
            ) last on true
            order by last.created_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()


def delete_message(message_id: int) -> int | None:
    """쪽지 하나를 지우고, 그 쪽지가 있던 대화의 회원 번호를 돌려준다(없었으면 None)."""
    with pool.connection() as conn:
        row = conn.execute("delete from messages where id = %s returning user_id", (message_id,)).fetchone()
    return row["user_id"] if row else None
