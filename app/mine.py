"""내가 등록한 물건 (/my): 로그인한 채로 등록한 사람은 자기 물건을 직접 관리할 수 있다.

할 수 있는 것: '주인 찾음' 표시(찾아간 사람 이름·학번 기록), 숨기기·다시 보이기, 지우기.
사진의 개인정보 확인은 선생님(관리자)만 한다.
누구 물건인지는 등록할 때 저장한 items.user_id로 확인한다. 로그인하지 않고 등록한 물건은 관리자만 관리한다.
"""
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from . import auth, db
from .admin import remove_item, update_hidden, update_status
from .templating import templates

log = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/my")


def _to_login() -> RedirectResponse:
    return RedirectResponse("/login?" + urlencode({"next": "/my"}), status_code=303)


def _back(message: str, item_id: int | None = None) -> RedirectResponse:
    """작업을 마치고 내 물건 목록으로 돌아간다. (303: 새로고침해도 같은 작업이 반복되지 않음)"""
    anchor = f"#item-{item_id}" if item_id else ""
    return RedirectResponse("/my?" + urlencode({"msg": message}) + anchor, status_code=303)


def _check_owner(request: Request, item_id: int) -> dict | None:
    """로그인한 사람을 돌려준다. 로그인 안 했으면 None, 남의 물건이면 403."""
    user = auth.current_user(request)
    if user is None:
        return None
    if db.item_owner(item_id) != user["id"]:
        raise HTTPException(status_code=403, detail="내가 등록한 물건만 바꿀 수 있어요.")
    return user


@router.get("")
def my_home(request: Request, msg: str = ""):
    user = auth.current_user(request)
    if user is None:
        return _to_login()
    return templates.TemplateResponse(
        request, "my_items.html", {"items": db.my_items(user["id"]), "message": msg[:200]}
    )


@router.post("/items/{item_id}/status")
def change_status(
    request: Request,
    item_id: int,
    status: str = Form(...),
    claimant_name: str = Form(""),
    claimant_student_id: str = Form(""),
):
    user = _check_owner(request, item_id)
    if user is None:
        return _to_login()
    message = update_status(item_id, status, claimant_name, claimant_student_id)
    log.info("%s님이 자기 물건 %s번을 '%s'(으)로 바꿈", user["username"], item_id, status)
    return _back(message, item_id)


@router.post("/items/{item_id}/hidden")
def change_hidden(request: Request, item_id: int, hidden: bool = Form(...)):
    user = _check_owner(request, item_id)
    if user is None:
        return _to_login()
    log.info("%s님이 자기 물건 %s번 %s", user["username"], item_id, "숨김" if hidden else "다시 보이기")
    return _back(update_hidden(item_id, hidden), item_id)


@router.post("/items/{item_id}/delete")
def delete(request: Request, item_id: int):
    user = _check_owner(request, item_id)
    if user is None:
        return _to_login()
    log.info("%s님이 자기 물건 %s번을 지움", user["username"], item_id)
    return _back(remove_item(item_id))
