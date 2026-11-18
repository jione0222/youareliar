"""쪽지함: 회원이 관리자(선생님)에게 쪽지로 문의하고 답장을 받는다.

- 회원(/inbox): 관리자와 주고받은 쪽지를 보고 새 쪽지를 보낸다. 로그인해야 쓸 수 있다(답장을 받을 곳이 필요해서).
  물건 상세 화면의 '관리자에게 쪽지로 문의'를 누르면 그 물건 번호가 쪽지에 붙는다.
  예: 내 물건인데 다른 사람이 찾아갔다고 나올 때 → 관리자가 그 물건의 '찾아간 사람' 기록을 확인한다.
- 관리자(/admin/inbox): 회원별 대화 목록을 보고 답장하거나, 장난 쪽지를 지운다.
  물건 관리 화면의 '등록한 사람에게 쪽지'로 등록한 회원에게 먼저 보낼 수도 있다.
- 쪽지는 그 회원과 관리자만 볼 수 있다. Claude나 검색에는 쓰지 않고, 서버 기록에도 내용은 남기지 않는다.
"""
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from . import auth, db
from .admin import is_admin
from .templating import templates

log = logging.getLogger("uvicorn.error")
router = APIRouter()

MAX_LENGTH = 1000  # 쪽지 한 개에 쓸 수 있는 글자 수
DAILY_LIMIT = 20  # 회원 한 명이 24시간 동안 보낼 수 있는 쪽지 수(장난 쪽지 막기)


def _parse_id(text: str | None) -> int | None:
    """주소나 폼에서 받은 번호. 숫자가 아니면 None."""
    text = (text or "").strip()
    return int(text) if text.isdigit() and len(text) < 19 else None


def _check_body(body: str) -> tuple[str, str | None]:
    """쪽지 내용을 다듬고, 문제가 있으면 오류 메시지를 함께 돌려준다."""
    text = body.strip().replace("\r\n", "\n")
    if not text:
        return text, "쪽지 내용을 적어 주세요."
    if len(text) > MAX_LENGTH:
        return text, f"쪽지는 {MAX_LENGTH}자까지 쓸 수 있어요. 지금 {len(text)}자예요."
    return text, None


# ---------- 회원 ----------


def _item_for(user: dict, item_id: int | None) -> dict | None:
    """쪽지에 붙일 물건. 없는 물건이나 남이 숨긴 글은 붙이지 않는다."""
    if item_id is None:
        return None
    item = db.item_brief(item_id)
    if item is None or (item["hidden"] and item["user_id"] != user["id"]):
        return None
    return item


def _render_inbox(request: Request, user: dict, about: dict | None, body: str = "",
                  error: str | None = None, message: str = "", status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "messages": db.thread(user["id"]),
            "about": about,
            "body": body,
            "error": error,
            "message": message,
            "max_length": MAX_LENGTH,
        },
        status_code=status_code,
    )


@router.get("/inbox")
def inbox(request: Request, item: str = "", msg: str = ""):
    user = auth.current_user(request)
    if user is None:
        here = "/inbox" + (f"?item={_parse_id(item)}" if _parse_id(item) else "")
        return RedirectResponse("/login?" + urlencode({"next": here}), status_code=303)
    db.mark_read(user["id"], from_admin=True)  # 관리자가 보낸 쪽지를 읽음으로 표시
    return _render_inbox(request, user, _item_for(user, _parse_id(item)), message=msg[:200])


@router.post("/inbox")
def send(request: Request, body: str = Form(""), item_id: str = Form("")):
    user = auth.current_user(request)
    if user is None:
        return RedirectResponse("/login?" + urlencode({"next": "/inbox"}), status_code=303)
    about = _item_for(user, _parse_id(item_id))
    text, error = _check_body(body)
    if error is None and db.sent_today(user["id"]) >= DAILY_LIMIT:
        error = f"쪽지는 하루에 {DAILY_LIMIT}개까지 보낼 수 있어요. 내일 다시 보내 주세요."
    if error:
        return _render_inbox(request, user, about, body=text, error=error, status_code=400)
    db.add_message(user["id"], text, item_id=about["id"] if about else None)
    log.info("%s님이 관리자에게 쪽지를 보냄%s", user["username"], f" ({about['id']}번 물건)" if about else "")
    done = "관리자에게 쪽지를 보냈어요. 답장이 오면 위쪽에 '쪽지' 표시가 떠요."
    return RedirectResponse("/inbox?" + urlencode({"msg": done}) + "#latest", status_code=303)


# ---------- 관리자 ----------


def _to_admin_login() -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=303)


def _render_thread(request: Request, member: dict, about_id: int | None, body: str = "",
                   error: str | None = None, message: str = "", status_code: int = 200):
    messages = db.thread(member["id"])
    item_ids = {m["item_id"] for m in messages if m["item_id"]}
    if about_id:
        item_ids.add(about_id)
    return templates.TemplateResponse(
        request,
        "admin_thread.html",
        {
            "member": member,
            "messages": messages,
            "related": db.manage_items_by_ids(sorted(item_ids)),  # 쪽지에 나온 물건(찾아간 사람 기록 포함)
            "about_id": about_id,
            "body": body,
            "error": error,
            "message": message,
            "max_length": MAX_LENGTH,
        },
        status_code=status_code,
    )


@router.get("/admin/inbox")
def admin_inbox(request: Request):
    if not is_admin(request):
        return _to_admin_login()
    return templates.TemplateResponse(request, "admin_inbox.html", {"conversations": db.conversations()})


@router.get("/admin/inbox/{user_id}")
def admin_thread(request: Request, user_id: int, item: str = "", msg: str = ""):
    if not is_admin(request):
        return _to_admin_login()
    member = db.get_user(user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="없는 회원이에요.")
    db.mark_read(user_id, from_admin=False)  # 회원이 보낸 쪽지를 읽음으로 표시
    about_id = _parse_id(item)
    if about_id and db.item_brief(about_id) is None:
        about_id = None
    return _render_thread(request, member, about_id, message=msg[:200])


@router.post("/admin/inbox/{user_id}")
def admin_reply(request: Request, user_id: int, body: str = Form(""), item_id: str = Form("")):
    if not is_admin(request):
        return _to_admin_login()
    member = db.get_user(user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="없는 회원이에요.")
    about_id = _parse_id(item_id)
    if about_id and db.item_brief(about_id) is None:
        about_id = None
    text, error = _check_body(body)
    if error:
        return _render_thread(request, member, about_id, body=text, error=error, status_code=400)
    db.add_message(user_id, text, from_admin=True, item_id=about_id)
    log.info("관리자가 %s님에게 쪽지를 보냄", member["username"])
    return RedirectResponse(
        f"/admin/inbox/{user_id}?" + urlencode({"msg": "쪽지를 보냈어요."}) + "#latest", status_code=303
    )


@router.post("/admin/inbox/messages/{message_id}/delete")
def admin_delete_message(request: Request, message_id: int):
    if not is_admin(request):
        return _to_admin_login()
    user_id = db.delete_message(message_id)
    log.info("관리자가 쪽지 %s번을 지움", message_id)
    if user_id is None:
        return RedirectResponse("/admin/inbox", status_code=303)
    return RedirectResponse(f"/admin/inbox/{user_id}?" + urlencode({"msg": "쪽지를 지웠어요."}), status_code=303)
