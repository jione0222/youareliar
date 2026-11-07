"""회원가입·로그인·로그아웃 화면.

학교 인증이나 이메일 인증은 하지 않는다(필요하면 나중에 붙인다).
"""
import re
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from . import auth, db
from .templating import templates

router = APIRouter()

USERNAME_RULE = re.compile(r"^[a-z0-9_]{4,20}$")  # 영어 소문자·숫자·밑줄(_), 4~20자


def _safe_next(next_url: str) -> str:
    """로그인 뒤 돌아갈 주소. 우리 사이트 안의 주소만 허락한다(다른 사이트로 빼돌리지 못하게)."""
    if next_url.startswith("/") and not next_url.startswith("//") and "\\" not in next_url:
        return next_url
    return "/"


def _logged_in_response(user_id: int, next_url: str, request: Request) -> RedirectResponse:
    response = RedirectResponse(_safe_next(next_url), status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.start_session(user_id),
        max_age=auth.SESSION_DAYS * 24 * 60 * 60,
        httponly=True,  # 화면의 자바스크립트가 읽지 못하게
        samesite="lax",  # 다른 사이트가 몰래 요청을 보내지 못하게
        secure=request.url.scheme == "https",
    )
    return response


# ---------- 회원가입 ----------


@router.get("/signup")
def signup_form(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "signup.html", {"error": None, "values": {}, "next": next})


@router.post("/signup")
def signup(
    request: Request,
    username: str = Form(""),
    nickname: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
    next: str = Form("/"),
):
    username = username.strip().lower()
    nickname = nickname.strip()
    values = {"username": username, "nickname": nickname}

    def fail(message: str):
        return templates.TemplateResponse(
            request, "signup.html", {"error": message, "values": values, "next": next}, status_code=400
        )

    if not USERNAME_RULE.match(username):
        return fail("아이디는 영어 소문자, 숫자, 밑줄(_)로 4~20자로 만들어 주세요.")
    if not 1 <= len(nickname) <= 20:
        return fail("닉네임은 1~20자로 적어 주세요.")
    if not 8 <= len(password) <= 128:
        return fail("비밀번호는 8자 이상으로 정해 주세요.")
    if password != password_confirm:
        return fail("비밀번호 확인이 달라요. 같은 비밀번호를 두 번 넣어 주세요.")

    user_id = db.create_user(username, auth.hash_password(password), nickname)
    if user_id is None:
        return fail("이미 있는 아이디예요. 다른 아이디를 골라 주세요.")
    return _logged_in_response(user_id, next, request)  # 가입하면 바로 로그인


# ---------- 로그인 / 로그아웃 ----------


@router.get("/login")
def login_form(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "login.html", {"error": None, "username": "", "next": next})


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("/")):
    username = username.strip().lower()
    user = db.get_user_by_username(username)
    if user and auth.verify_password(password, user["password_hash"]):
        return _logged_in_response(user["id"], next, request)
    time.sleep(1)  # 비밀번호를 마구 넣어 보는 걸 느리게 만든다
    # 아이디가 틀렸는지 비밀번호가 틀렸는지는 알려 주지 않는다(아이디 알아내기 방지).
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "아이디 또는 비밀번호가 맞지 않아요.", "username": username, "next": next},
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.end_session(token)  # DB에서 지워서, 같은 표시로 다시 로그인되지 않게
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response
