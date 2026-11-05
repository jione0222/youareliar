"""설정값을 환경변수에서 읽어 오는 곳.

비밀번호나 키를 코드에 직접 적지 않고, 프로젝트 폴더의 .env 파일에 적어 둔다.
load_dotenv()가 .env 파일을 읽어 환경변수로 등록해 준다.
"""
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _stop(message: str) -> None:
    """설정이 잘못됐을 때, 긴 오류 대신 고칠 방법을 한국어로 보여 주고 멈춘다."""
    raise SystemExit(f"\n[설정 오류] {message}\n.env 파일을 고친 뒤 다시 실행해 주세요. (메모장으로 열기: notepad .env)\n")


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
# 둘 다 비어 있으면 '연습 모드': 사진을 내 컴퓨터의 uploads 폴더에 저장한다.
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "photos").strip()

# A 검색에 쓸 수 있는 AI 모델: 이름 → Hugging Face 모델 주소
EMBED_MODELS = {
    "siglip2-base": "google/siglip2-base-patch16-256",
}
EMBED_MODEL = os.getenv("EMBED_MODEL", "siglip2-base").strip()

# B 단계: Claude API. 둘 다 있어야 동작하고, 없으면 B 기능만 꺼진다(A 검색은 그대로).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "").strip()

# 서버가 해외에 있어도 날짜는 한국 시간으로 계산한다.
TIMEZONE = ZoneInfo("Asia/Seoul")

# ---------- 자주 하는 실수 미리 잡기 ----------
if not DATABASE_URL:
    _stop("DATABASE_URL이 비어 있어요. .env.example을 복사해 .env 파일을 만들고 값을 채워 주세요.")
if "[YOUR-PASSWORD]" in DATABASE_URL:
    _stop("DATABASE_URL의 [YOUR-PASSWORD]를 실제 DB 비밀번호로 바꿔 주세요. 대괄호 [ ]도 지워야 해요.")
for name, value in [
    ("DATABASE_URL", DATABASE_URL),
    ("SUPABASE_URL", SUPABASE_URL),
    ("SUPABASE_SECRET_KEY", SUPABASE_SECRET_KEY),
    ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    ("CLAUDE_MODEL", CLAUDE_MODEL),
]:
    if not value.isascii():
        _stop(
            f"{name}에 한글 같은 글자가 들어 있어요. 주소·비밀번호·키는 영어와 숫자로만 되어 있어야 해요.\n"
            "'비밀번호', '키', '프로젝트ID' 같은 예시 글자를 실제 값으로 바꿨는지 확인해 주세요."
        )
if ANTHROPIC_API_KEY and not ANTHROPIC_API_KEY.startswith("sk-ant-"):
    _stop("ANTHROPIC_API_KEY는 sk-ant- 로 시작해야 해요. Claude 콘솔에서 만든 키를 통째로 복사해 넣어 주세요.")
if ANTHROPIC_API_KEY and not CLAUDE_MODEL:
    _stop("ANTHROPIC_API_KEY는 있는데 CLAUDE_MODEL이 비어 있어요. 쓸 Claude 모델 이름을 넣어 주세요(README 참고).")
if EMBED_MODEL not in EMBED_MODELS:
    _stop(f"EMBED_MODEL '{EMBED_MODEL}'은 없는 모델이에요. 쓸 수 있는 모델: {', '.join(EMBED_MODELS)}")
if SUPABASE_URL:
    if not SUPABASE_URL.startswith("https://"):
        _stop("SUPABASE_URL은 https:// 로 시작해야 해요. 예: https://abcd1234.supabase.co")
    if not SUPABASE_SECRET_KEY:
        _stop("SUPABASE_SECRET_KEY가 비어 있어요. Supabase의 Project Settings → API Keys에서 Secret key를 복사해 넣어 주세요.")
    if SUPABASE_SECRET_KEY.startswith("sb_publishable_"):
        _stop("SUPABASE_SECRET_KEY에 publishable 키가 들어 있어요. sb_secret_ 로 시작하는 Secret key를 넣어 주세요.")
