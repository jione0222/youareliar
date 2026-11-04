"""휴대폰 사진을 웹에 올리기 좋게 바꾸는 곳.

휴대폰 사진은 한 장에 3~10MB나 돼서, 그대로 쓰면 목록을 여는 데 오래 걸린다.
그래서 두 가지 크기로 줄여 저장한다.
- 상세 화면용: 긴 변 1280px
- 목록용 작은 사진(썸네일): 긴 변 480px
"""
from io import BytesIO

from PIL import Image, ImageOps

PHOTO_MAX_SIDE = 1280
THUMB_MAX_SIDE = 480


class NotAnImage(Exception):
    """사진 파일이 아니거나 열 수 없는 파일일 때."""


def prepare(raw: bytes) -> tuple[bytes, bytes]:
    """원본 사진을 받아 (상세용 JPEG, 목록용 JPEG)를 돌려준다."""
    try:
        img = Image.open(BytesIO(raw))
        # 휴대폰은 사진을 '눕힌 채' 저장하고 회전 정보만 따로 적어 두기도 한다.
        # 그 회전을 실제로 적용해야 사진이 옆으로 누워 보이지 않는다.
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except Exception as error:
        raise NotAnImage() from error
    return _to_jpeg(img, PHOTO_MAX_SIDE, quality=85), _to_jpeg(img, THUMB_MAX_SIDE, quality=80)


def _to_jpeg(img: Image.Image, max_side: int, quality: int) -> bytes:
    small = img.copy()
    small.thumbnail((max_side, max_side))  # 비율은 유지하면서 긴 변을 max_side 이하로
    buffer = BytesIO()
    # EXIF(찍은 위치 GPS, 기종 등) 정보는 일부러 저장하지 않는다 — 개인정보 보호.
    small.save(buffer, "JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
