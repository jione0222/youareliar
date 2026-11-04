"""설정값을 환경변수에서 읽어 오는 곳.

비밀번호나 키를 코드에 직접 적지 않고, 프로젝트 폴더의 .env 파일에 적어 둔다.
load_dotenv()가 .env 파일을 읽어 환경변수로 등록해 준다.
"""
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL이 없습니다. .env.example을 복사해 .env 파일을 만들고 값을 채워 주세요."
    )

# 둘 다 비어 있으면 '연습 모드': 사진을 내 컴퓨터의 uploads 폴더에 저장한다.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "photos")

# 서버가 해외에 있어도 날짜는 한국 시간으로 계산한다.
TIMEZONE = ZoneInfo("Asia/Seoul")
