"""웹 서버의 시작점. 주소(URL)마다 어떤 화면을 보여 줄지 정한다.

실행:  uvicorn app.main:app --reload
"""
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException

from . import config, db, images, storage

APP_DIR = Path(__file__).resolve().parent
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15MB보다 큰 파일은 받지 않는다

# 등록 화면에서 보관 장소로 추천할 곳 (목록에 없으면 직접 입력하면 된다)
STORAGE_PLACE_SUGGESTIONS = ["교무실", "행정실", "체육관 사무실", "도서관", "보건실"]

# DB에는 영어 코드로 저장하고, 화면에는 한국어로 보여 준다.
STATUS_LABELS = {"stored": "보관 중", "returned": "주인 찾음"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.pool.open()  # 서버가 켜질 때 DB 연결을 준비하고
    yield
    db.pool.close()  # 서버가 꺼질 때 정리한다


app = FastAPI(title="학교 분실물 AI 찾기", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
if not storage.using_supabase():
    # 연습 모드: uploads 폴더의 사진을 /uploads/... 주소로 보여 준다.
    storage.LOCAL_DIR.mkdir(exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=storage.LOCAL_DIR), name="uploads")

templates = Jinja2Templates(directory=APP_DIR / "templates")


def korean_date(value: date | datetime | None) -> str:
    """날짜를 '11월 4일'처럼, 시각까지 있으면 '11월 4일 14:05'처럼 보여 준다."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.astimezone(config.TIMEZONE)
        return f"{value.month}월 {value.day}일 {value:%H:%M}"
    return f"{value.month}월 {value.day}일"


# 템플릿(HTML) 안에서 쓸 수 있게 등록해 둔다.
templates.env.globals["photo_url"] = storage.public_url
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
templates.env.filters["korean_date"] = korean_date


def today() -> date:
    return datetime.now(config.TIMEZONE).date()


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
    item_id = db.add_item(
        photo_path, thumb_path, storage_place, found_place or None, parsed_date, memo or None
    )

    # 5) 상세 화면으로 보낸다. 303으로 보내면 새로고침해도 두 번 등록되지 않는다.
    return RedirectResponse(f"/items/{item_id}?new=1", status_code=303)


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
