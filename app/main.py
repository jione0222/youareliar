"""웹 서버의 시작점. 주소(URL)마다 어떤 화면을 보여 줄지 정한다.

실행:  uvicorn app.main:app --reload
"""
import logging
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from . import accounts, admin, auth, db, embedding, images, indexing, rerank, search, storage
from .templating import templates, today

APP_DIR = Path(__file__).resolve().parent
log = logging.getLogger("uvicorn.error")
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15MB보다 큰 파일은 받지 않는다

# 등록 화면에서 보관 장소로 추천할 곳 (목록에 없으면 직접 입력하면 된다)
STORAGE_PLACE_SUGGESTIONS = ["교무실", "행정실", "체육관 사무실", "도서관", "보건실"]

# DB에 연결하지 못했을 때: 오류 글자에 들어 있는 말 → 고치는 방법 (자주 나오는 것만)
DB_ERROR_HINTS = [
    (("password authentication failed",), "DATABASE_URL의 비밀번호가 틀렸어요. 대괄호 [ ]까지 지우고 비밀번호만 넣었는지 확인하세요."),
    (("Tenant or user not found",), "DATABASE_URL의 사용자 이름이 틀렸어요. Supabase의 Connect → Session pooler 주소를 다시 복사하세요."),
    (("failed to resolve host", "could not translate host name", "getaddrinfo failed"), "DATABASE_URL의 주소(@ 뒤쪽)가 틀렸거나 인터넷이 끊겼어요."),
    (("Network is unreachable",), "DB 주소로 가는 길이 없어요. Supabase의 Direct connection 주소 대신 Session pooler 주소를 쓰세요."),
    (("timeout expired",), "10초 안에 연결되지 않았어요. 인터넷이 느리거나, 이 서버에서 DB 포트(5432)로 나가는 연결이 막혀 있어요. (Hugging Face Spaces는 80·443·8080 포트만 열려 있어서 안 돼요.)"),
    (("Connection refused",), "DB가 꺼져 있거나 주소·포트가 틀렸어요. 이 컴퓨터의 Postgres를 쓴다면 켜져 있는지 확인하세요."),
]


def _check_db() -> None:
    """서버가 켜질 때 DB에 연결되는지 확인하고, 안 되면 고치는 방법을 서버 기록에 남긴다."""
    error = db.check_connection()
    if error is None:
        log.info("DB에 연결했어요.")
        return
    hint = next((h for words, h in DB_ERROR_HINTS if any(w in error for w in words)), "DATABASE_URL 값을 다시 확인하세요.")
    log.error("[DB 연결 실패] %s\n  오류 내용: %s", hint, error.splitlines()[0])


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.pool.open()  # 서버가 켜질 때 DB 연결을 준비하고
    threading.Thread(target=_check_db, daemon=True).start()  # 정말 연결되는지 확인한다
    # AI 모델은 불러오는 데 시간이 걸려서, 서버를 먼저 띄우고 뒤에서(별도 스레드) 준비한다.
    threading.Thread(target=indexing.warm_up, daemon=True).start()
    yield
    db.pool.close()  # 서버가 꺼질 때 정리한다


app = FastAPI(title="학교 분실물 AI 찾기", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
if not storage.using_supabase():
    # 연습 모드: uploads 폴더의 사진을 /uploads/... 주소로 보여 준다.
    storage.LOCAL_DIR.mkdir(exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=storage.LOCAL_DIR), name="uploads")

app.include_router(admin.router)  # 관리자 화면 (/admin)
app.include_router(accounts.router)  # 회원가입·로그인 (/signup, /login, /logout)

# ---------- 화면 ----------


@app.get("/")
def item_list(request: Request):
    """첫 화면: 최근 등록된 습득물 목록."""
    return templates.TemplateResponse(request, "list.html", {"items": db.list_items()})


@app.get("/register")
def register_form(request: Request):
    """습득물 등록 화면."""
    return render_register(request, values={"found_date": today().isoformat()})


@app.post("/register")
def register(
    request: Request,
    background_tasks: BackgroundTasks,
    photo_camera: UploadFile | None = File(None),  # '카메라로 찍기' 버튼으로 고른 사진
    photo_album: UploadFile | None = File(None),  # '앨범에서 고르기' 버튼으로 고른 사진
    storage_place: str = Form(""),
    found_place: str = Form(""),
    found_date: str = Form(""),
    memo: str = Form(""),
):
    """등록 화면에서 [등록하기]를 누르면 여기로 온다."""
    values = {
        "storage_place": storage_place,
        "found_place": found_place,
        "found_date": found_date,
        "memo": memo,
    }

    def fail(message: str):
        # 입력한 내용은 그대로 둔 채 등록 화면을 다시 보여 준다(사진만 다시 골라야 한다).
        return render_register(request, values=values, error=message, status_code=400)

    # 1) 입력값 확인 — 브라우저에서 한 번 막더라도, 서버에서 반드시 다시 확인한다.
    storage_place = storage_place.strip()
    found_place = found_place.strip()
    memo = memo.strip()
    if not storage_place:
        return fail("보관 장소를 적어 주세요.")
    if len(storage_place) > 50 or len(found_place) > 50:
        return fail("장소는 50자 이내로 적어 주세요.")
    if len(memo) > 500:
        return fail("메모는 500자 이내로 적어 주세요.")
    parsed_date = None
    if found_date:
        try:
            parsed_date = date.fromisoformat(found_date)
        except ValueError:
            return fail("발견 날짜를 다시 골라 주세요.")
        if parsed_date > today():
            return fail("발견 날짜가 오늘보다 뒤일 수는 없어요.")

    photo = next((f for f in (photo_camera, photo_album) if f is not None and f.filename), None)
    if photo is None:
        return fail("사진을 찍거나 골라 주세요.")
    raw = photo.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        return fail("사진이 너무 커요. 15MB 이하인 사진만 올릴 수 있어요.")

    # 2) 사진을 두 가지 크기로 줄인다.
    try:
        photo_jpeg, thumb_jpeg = images.prepare(raw)
    except images.NotAnImage:
        return fail("사진 파일만 올릴 수 있어요. 다른 사진으로 다시 해 주세요.")

    # 3) 겹치지 않는 무작위 이름으로 사진을 저장한다.
    key = uuid.uuid4().hex
    photo_path = f"items/{key}.jpg"
    thumb_path = f"items/{key}_thumb.jpg"
    storage.save(photo_path, photo_jpeg)
    storage.save(thumb_path, thumb_jpeg)

    # 4) 물건 정보를 DB에 저장한다.
    user = auth.current_user(request)  # 로그인했으면 누가 등록했는지 적어 둔다
    item_id = db.add_item(
        photo_path,
        thumb_path,
        storage_place,
        found_place or None,
        parsed_date,
        memo or None,
        user_id=user["id"] if user else None,
    )

    # 5) AI 검색을 위해 사진을 벡터로 바꿔 저장한다.
    indexing.index_photo(item_id, photo_jpeg)
    # B 단계: Claude 설명은 몇 초 걸리므로, 화면을 먼저 보여 주고 뒤에서 처리한다.
    background_tasks.add_task(indexing.describe_item, item_id, photo_jpeg, memo or None)

    # 6) 상세 화면으로 보낸다. 303으로 보내면 새로고침해도 두 번 등록되지 않는다.
    return RedirectResponse(f"/items/{item_id}?new=1", status_code=303)


@app.get("/search")
def search_page(request: Request, q: str = "", debug: bool = False):
    """AI 검색: 사진 벡터·설명 벡터·키워드로 찾은 순위를 합쳐서 비슷한 물건부터 보여 준다.
    주소 끝에 &debug=1 을 붙이면 카드마다 방법별 등수가 보인다(발표·시험용)."""
    query = q.strip()[:100]
    if not query:
        return RedirectResponse("/", status_code=303)
    context = {
        "q": query,
        "items": [],
        "ai_status": embedding.status(),
        "uses_descriptions": embedding.text_status() == "ready",
        "rerank_enabled": rerank.enabled(),
        "debug": debug,
    }
    if embedding.status() == "ready":
        context["items"] = search.search(query)
    return templates.TemplateResponse(request, "search.html", context)


@app.get("/search/rerank")
def search_rerank(q: str = "", ids: str = ""):
    """재순위: 검색 화면이 결과를 먼저 보여 준 뒤, 자바스크립트로 이 주소를 불러서
    Claude가 다시 정한 순서와 이유를 받아 간다. 예: /search/rerank?q=파란 텀블러&ids=3,1,7"""
    if not rerank.enabled():
        return JSONResponse({"error": "재순위가 꺼져 있어요(Claude 키 없음)."}, status_code=404)
    query = q.strip()[:100]
    try:
        item_ids = [int(part) for part in ids.split(",") if part.strip()][: rerank.MAX_CANDIDATES]
    except ValueError:
        return JSONResponse({"error": "후보 번호가 이상해요."}, status_code=400)
    if not query or len(item_ids) < 2:
        return {"ranking": []}
    try:
        return {"ranking": rerank.rerank(query, item_ids)}
    except rerank.LimitReached:
        return JSONResponse({"error": "오늘 쓸 수 있는 재순위 횟수를 다 썼어요."}, status_code=429)
    except Exception:
        log.exception("재순위를 하지 못했어요.")
        return JSONResponse({"error": "재순위를 하지 못했어요."}, status_code=502)


@app.get("/items/{item_id}")
def item_detail(request: Request, item_id: int, new: bool = False):
    """습득물 하나의 상세 화면."""
    item = db.get_item(item_id)
    if item is None or item["hidden"]:
        raise HTTPException(status_code=404, detail="찾는 물건이 없어요. 이미 지워졌을 수 있어요.")
    return templates.TemplateResponse(request, "item.html", {"item": item, "new": new})


# ---------- 도우미 ----------


def render_register(request: Request, values: dict, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "values": values,
            "error": error,
            "suggestions": STORAGE_PLACE_SUGGESTIONS,
            "today": today().isoformat(),
        },
        status_code=status_code,
    )


@app.exception_handler(HTTPException)
def show_error_page(request: Request, error: HTTPException):
    """오류가 나면 JSON 대신 사람이 읽을 수 있는 화면을 보여 준다."""
    if error.status_code == 404:
        # 없는 주소로 들어오면 FastAPI가 영어로 "Not Found"를 주므로 한국어로 바꾼다.
        message = "페이지를 찾을 수 없어요." if error.detail == "Not Found" else error.detail
    else:
        message = "문제가 생겼어요. 잠시 뒤 다시 해 주세요."
    return templates.TemplateResponse(
        request, "error.html", {"message": message}, status_code=error.status_code
    )
