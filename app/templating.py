"""화면(HTML 템플릿) 설정. 일반 화면(main.py)과 관리자 화면(admin.py)이 같이 쓴다."""
from datetime import date, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from . import auth, config, describe, storage

APP_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=APP_DIR / "templates")

# DB에는 영어 코드로 저장하고, 화면에는 한국어로 보여 준다.
STATUS_LABELS = {"stored": "보관 중", "returned": "주인 찾음"}


def korean_date(value: date | datetime | None) -> str:
    """날짜를 '11월 4일'처럼, 시각까지 있으면 '11월 4일 14:05'처럼 보여 준다."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.astimezone(config.TIMEZONE)
        return f"{value.month}월 {value.day}일 {value:%H:%M}"
    return f"{value.month}월 {value.day}일"


def privacy_flagged(item: dict) -> bool:
    """Claude가 사진에서 사람 얼굴이나 개인정보(이름·학번 등)를 봤는지."""
    info = item.get("ai_info") or {}
    return bool(info.get("has_person_face") or info.get("has_personal_info"))


def photo_hidden(item: dict) -> bool:
    """공개 화면에서 사진을 가릴지.
    .env의 HIDE_PRIVATE_PHOTOS가 켜져 있을 때만, 개인정보가 의심되는 사진을 관리자가 확인하기 전까지 가린다."""
    return config.HIDE_PRIVATE_PHOTOS and privacy_flagged(item) and not item.get("privacy_reviewed")


def today() -> date:
    return datetime.now(config.TIMEZONE).date()


# 템플릿(HTML) 안에서 쓸 수 있게 등록해 둔다.
templates.env.globals["photo_url"] = storage.public_url
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS
templates.env.globals["photo_hidden"] = photo_hidden
templates.env.globals["privacy_flagged"] = privacy_flagged
templates.env.globals["HIDE_PRIVATE_PHOTOS"] = config.HIDE_PRIVATE_PHOTOS
templates.env.globals["ai_enabled"] = describe.enabled
templates.env.globals["current_user"] = auth.current_user
templates.env.filters["korean_date"] = korean_date
