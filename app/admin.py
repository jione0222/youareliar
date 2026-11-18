"""관리자 화면 (/admin): 장난 글 숨기기·지우기, '주인 찾음' 표시(찾아간 사람 기록), 가린 사진 확인,
물건 정보 고치기(제목·장소·날짜·메모·종류·연락처·찾아간 사람).
쪽지함(회원 문의)은 inbox.py에 있다.

관리자인지 확인하는 방법
- .env의 ADMIN_PASSWORD를 아는 사람만 들어올 수 있다.
- 로그인하면 브라우저에 '관리자 표시'(쿠키)를 저장해 두고, 요청마다 그 표시가 진짜인지 확인한다.
- 표시는 비밀번호로 서명(HMAC)해서 만들기 때문에, 비밀번호를 모르면 흉내 낼 수 없다.
"""
import hashlib
import hmac
import logging
import time
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException

from . import categories, config, db, indexing, storage
from .forms import normalize_phone
from .templating import STATUS_LABELS, templates, today

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


# ---------- 작업 (관리자 화면과 '내가 등록한 물건'이 함께 쓴다) ----------


def update_status(item_id: int, status: str, claimant_name: str = "", claimant_student_id: str = "") -> str:
    """상태를 바꾸고 결과 메시지를 돌려준다. '주인 찾음'이면 찾아간 사람(이름·학번)도 적는다."""
    if status not in STATUS_LABELS:
        raise HTTPException(status_code=400)
    name = claimant_name.strip()[:20] or None
    student_id = claimant_student_id.strip()[:20] or None
    db.set_status(item_id, status, name, student_id)
    # 이 메시지는 주소(?msg=)에 붙어서 기록에 남을 수 있으니 이름·학번은 넣지 않는다.
    noted = " 찾아간 사람도 적어 뒀어요(관리자만 볼 수 있어요)." if status == "returned" and (name or student_id) else ""
    return f"{item_id}번을 '{STATUS_LABELS[status]}'(으)로 바꿨어요.{noted}"


def update_hidden(item_id: int, hidden: bool) -> str:
    db.set_hidden(item_id, hidden)
    return f"{item_id}번을 {'숨겼어요' if hidden else '다시 보이게 했어요'}."


def remove_item(item_id: int) -> str:
    """물건과 사진 파일을 지우고 결과 메시지를 돌려준다."""
    removed = db.delete_item(item_id)
    if removed is None:
        return f"{item_id}번은 이미 없어요."
    try:
        storage.delete([removed["photo_path"], removed["thumb_path"]])
    except Exception:
        log.exception("%s번의 사진 파일을 지우지 못했어요(글은 지워졌어요).", item_id)
    return f"{item_id}번을 지웠어요."


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
            "unread": db.unread_for_admin(),  # 아직 안 읽은 회원 쪽지 수
            "message": msg[:200],
        },
    )


@router.post("/items/{item_id}/status")
def change_status(
    request: Request,
    item_id: int,
    status: str = Form(...),
    claimant_name: str = Form(""),
    claimant_student_id: str = Form(""),
    view: str = Form("all"),
):
    if not is_admin(request):
        return _to_login()
    message = update_status(item_id, status, claimant_name, claimant_student_id)
    log.info("관리자: %s번을 '%s'(으)로 바꿈", item_id, STATUS_LABELS[status])
    return _back(view, message)


@router.post("/items/{item_id}/hidden")
def change_hidden(request: Request, item_id: int, hidden: bool = Form(...), view: str = Form("all")):
    if not is_admin(request):
        return _to_login()
    log.info("관리자: %s번 %s", item_id, "숨김" if hidden else "다시 보이기")
    return _back(view, update_hidden(item_id, hidden))


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
    log.info("관리자: %s번 지움", item_id)
    return _back(view, remove_item(item_id))


# ---------- 물건 정보 고치기 (제목, 장소, 날짜, 메모, 종류, 연락처, 찾아간 사람) ----------


def _render_edit(request: Request, item: dict, values: dict, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "admin_edit.html",
        {"item": item, "values": values, "error": error, "groups": categories.GROUPS, "today": today().isoformat()},
        status_code=status_code,
    )


@router.get("/items/{item_id}/edit")
def edit_form(request: Request, item_id: int):
    if not is_admin(request):
        return _to_login()
    item = db.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="없는 물건이에요.")
    values = {name: item[name] for name in db.EDITABLE}
    values["found_date"] = item["found_date"].isoformat() if item["found_date"] else ""
    return _render_edit(request, item, values)


@router.post("/items/{item_id}/edit")
def edit(
    request: Request,
    background_tasks: BackgroundTasks,
    item_id: int,
    title: str = Form(""),
    storage_place: str = Form(""),
    found_place: str = Form(""),
    found_date: str = Form(""),
    memo: str = Form(""),
    category: str = Form(""),
    finder_name: str = Form(""),
    finder_phone: str = Form(""),
    claimant_name: str = Form(""),
    claimant_student_id: str = Form(""),
):
    if not is_admin(request):
        return _to_login()
    item = db.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="없는 물건이에요.")
    form = {
        "title": " ".join(title.split()), "storage_place": storage_place.strip(), "found_place": found_place.strip(),
        "found_date": found_date.strip(), "memo": memo.strip(), "category": category,
        "finder_name": finder_name.strip(), "finder_phone": finder_phone.strip(),
        "claimant_name": claimant_name.strip(), "claimant_student_id": claimant_student_id.strip(),
    }

    def fail(message: str):
        return _render_edit(request, item, form, message, status_code=400)

    # 등록 화면과 같은 기준으로 확인한다.
    if not form["storage_place"]:
        return fail("보관 장소는 비울 수 없어요.")
    if len(form["title"]) > 40:
        return fail("제목은 40자까지 쓸 수 있어요.")
    if len(form["storage_place"]) > 50 or len(form["found_place"]) > 50:
        return fail("장소는 50자 이내로 적어 주세요.")
    if len(form["memo"]) > 500:
        return fail("메모는 500자 이내로 적어 주세요.")
    if any(len(form[name]) > 20 for name in ("finder_name", "claimant_name", "claimant_student_id")):
        return fail("이름·학번은 20자 이내로 적어 주세요.")
    parsed_date = None
    if form["found_date"]:
        try:
            parsed_date = date.fromisoformat(form["found_date"])
        except ValueError:
            return fail("발견 날짜를 다시 골라 주세요.")
        if parsed_date > today():
            return fail("발견 날짜가 오늘보다 뒤일 수는 없어요.")
    phone = form["finder_phone"]
    if phone:
        try:
            phone = normalize_phone(phone)
        except ValueError:
            return fail("전화번호를 다시 확인해 주세요. 예: 010-1234-5678")

    values = {
        "title": form["title"] or None,
        "storage_place": form["storage_place"],
        "found_place": form["found_place"] or None,
        "found_date": parsed_date,
        "memo": form["memo"] or None,
        "category": categories.clean(form["category"]) or item["category"],  # 비우면 원래 종류 그대로
        "finder_name": form["finder_name"] or None,
        "finder_phone": phone or None,
    }
    if item["status"] == "returned":  # 찾아간 사람 기록은 '주인 찾음'일 때만 고친다
        values["claimant_name"] = form["claimant_name"] or None
        values["claimant_student_id"] = form["claimant_student_id"] or None
    db.update_item(item_id, values)

    # 제목이나 메모가 바뀌면 AI 검색용 설명 벡터를 새로 만든다(키워드 검색은 바로 반영된다).
    if (values["title"], values["memo"]) != (item["title"], item["memo"]) and item["ai_info"]:
        db.delete_vector(item_id, "description")
        background_tasks.add_task(indexing.backfill_description_vectors)
    log.info("관리자: %s번 정보를 고침", item_id)
    return RedirectResponse(
        "/admin?" + urlencode({"view": "all", "msg": f"{item_id}번 정보를 고쳤어요."}) + f"#item-{item_id}",
        status_code=303,
    )
