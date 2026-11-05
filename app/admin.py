"""관리자 화면 (/admin): 장난 글 숨기기·지우기, '주인 찾음' 표시, 가린 사진 확인.

관리자인지 확인하는 방법
- .env의 ADMIN_PASSWORD를 아는 사람만 들어올 수 있다.
- 로그인하면 브라우저에 '관리자 표시'(쿠키)를 저장해 두고, 요청마다 그 표시가 진짜인지 확인한다.
- 표시는 비밀번호로 서명(HMAC)해서 만들기 때문에, 비밀번호를 모르면 흉내 낼 수 없다.
"""
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from . import config, db, storage
from .templating import STATUS_LABELS, templates

log = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/admin")

COOKIE_NAME = "admin_session"
SESSION_SECONDS = 7 * 24 * 60 * 60  # 한 번 로그인하면 7일 동안 유지

VIEW_LABELS = {"all": "전체", "privacy": "사진 확인 필요", "hidden": "숨긴 글", "returned": "주인 찾음"}


# ---------- 관리자 확인 ----------


def _sign(issued_at: str) -> str:
    return hmac.new(
        config.ADMIN_PASSWORD.encode(), f"admin:{issued_at}".encode(), hashlib.sha256
    ).hexdigest()


def _make_token() -> str:
    issued_at = str(int(time.time()))
    return f"{issued_at}.{_sign(issued_at)}"


def is_admin(request: Request) -> bool:
    """이 요청을 보낸 사람이 로그인한 관리자인지 확인한다."""
    if not config.ADMIN_PASSWORD:
        return False
    issued_at, _, signature = request.cookies.get(COOKIE_NAME, "").partition(".")
    if not issued_at.isdigit() or not signature:
        return False
    if time.time() - int(issued_at) > SESSION_SECONDS:
        return False  # 오래된 표시는 무효
    return hmac.compare_digest(signature, _sign(issued_at))


def _to_login() -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=303)


def _back(view: str, message: str) -> RedirectResponse:
    """작업을 마치고 관리자 목록으로 돌아간다. (303: 새로고침해도 같은 작업이 반복되지 않음)"""
    if view not in VIEW_LABELS:
        view = "all"
    return RedirectResponse("/admin?" + urlencode({"view": view, "msg": message}), status_code=303)


# ---------- 로그인 ----------


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(
        request, "admin_login.html", {"error": None, "enabled": bool(config.ADMIN_PASSWORD)}
    )


@router.post("/login")
def login(request: Request, password: str = Form("")):
    if config.ADMIN_PASSWORD and hmac.compare_digest(password.strip().encode(), config.ADMIN_PASSWORD.encode()):
        response = RedirectResponse("/admin", status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            _make_token(),
            max_age=SESSION_SECONDS,
            path="/admin",  # 관리자 화면에서만 쓰는 표시
            httponly=True,  # 화면의 자바스크립트가 읽지 못하게
            samesite="lax",  # 다른 사이트가 몰래 관리자 작업을 보내지 못하게
            secure=request.url.scheme == "https",
        )
        log.info("관리자가 로그인했어요.")
        return response
    time.sleep(1)  # 비밀번호를 마구 넣어 보는 걸 느리게 만든다
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {"error": "비밀번호가 맞지 않아요.", "enabled": bool(config.ADMIN_PASSWORD)},
        status_code=401,
    )


@router.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/admin")
    return response


# ---------- 목록과 작업 ----------


@router.get("")
def admin_home(request: Request, view: str = "all", msg: str = ""):
    if not is_admin(request):
        return _to_login()
    if view not in VIEW_LABELS:
        view = "all"
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "items": db.admin_list_items(view),
            "view": view,
            "views": VIEW_LABELS,
            "counts": db.admin_counts(),
            "message": msg[:200],
        },
    )


@router.post("/items/{item_id}/status")
def change_status(request: Request, item_id: int, status: str = Form(...), view: str = Form("all")):
    if not is_admin(request):
        return _to_login()
    if status not in STATUS_LABELS:
        raise HTTPException(status_code=400)
    db.set_status(item_id, status)
    log.info("관리자: %s번을 '%s'(으)로 바꿈", item_id, STATUS_LABELS[status])
    return _back(view, f"{item_id}번을 '{STATUS_LABELS[status]}'(으)로 바꿨어요.")


@router.post("/items/{item_id}/hidden")
def change_hidden(request: Request, item_id: int, hidden: bool = Form(...), view: str = Form("all")):
    if not is_admin(request):
        return _to_login()
    db.set_hidden(item_id, hidden)
    log.info("관리자: %s번 %s", item_id, "숨김" if hidden else "다시 보이기")
    return _back(view, f"{item_id}번을 {'숨겼어요' if hidden else '다시 보이게 했어요'}.")


@router.post("/items/{item_id}/privacy")
def change_privacy(request: Request, item_id: int, reviewed: bool = Form(...), view: str = Form("all")):
    if not is_admin(request):
        return _to_login()
    db.set_privacy_reviewed(item_id, reviewed)
    log.info("관리자: %s번 사진 %s", item_id, "공개 확인" if reviewed else "다시 가림")
    return _back(view, f"{item_id}번 사진을 {'공개했어요' if reviewed else '다시 가렸어요'}.")


@router.post("/items/{item_id}/delete")
def delete(request: Request, item_id: int, view: str = Form("all")):
    if not is_admin(request):
        return _to_login()
    removed = db.delete_item(item_id)
    if removed is None:
        return _back(view, f"{item_id}번은 이미 없어요.")
    try:
        storage.delete([removed["photo_path"], removed["thumb_path"]])
    except Exception:
        log.exception("%s번의 사진 파일을 지우지 못했어요(글은 지워졌어요).", item_id)
    log.info("관리자: %s번 지움", item_id)
    return _back(view, f"{item_id}번을 지웠어요.")
