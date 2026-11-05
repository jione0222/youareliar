"""AI 벡터를 만들어 DB에 넣는 일.

- 물건을 등록할 때: index_photo()가 사진 벡터를 만들어 저장한다.
- 서버가 켜질 때: backfill()이 벡터가 빠진 물건을 찾아 채운다.
  (AI 모델이 준비되기 전에 등록된 물건이나, 모델을 바꿨을 때를 위해)
"""
import logging
from io import BytesIO

from PIL import Image

from . import config, db, describe, embedding, storage

log = logging.getLogger("uvicorn.error")


def index_photo(item_id: int, photo_jpeg: bytes) -> bool:
    """사진 벡터를 만들어 저장한다. 실패해도 등록 자체는 막지 않는다(서버를 다시 켜면 다시 시도한다)."""
    try:
        vector = embedding.embed_image(Image.open(BytesIO(photo_jpeg)))
        db.save_vector(item_id, config.EMBED_MODEL, "image", vector)
        return True
    except Exception:
        log.exception("물건 %s번의 AI 벡터를 만들지 못했어요. 서버를 다시 켜면 다시 시도해요.", item_id)
        return False


def backfill() -> None:
    """벡터가 없는 물건을 모두 찾아 벡터를 만든다."""
    missing = db.items_missing_vector(config.EMBED_MODEL, "image")
    if not missing:
        return
    log.info("AI 벡터가 없는 물건 %d개를 처리할게요.", len(missing))
    done = 0
    for row in missing:
        try:
            photo = storage.load(row["photo_path"])
        except Exception:
            log.exception("물건 %s번의 사진을 읽지 못했어요.", row["id"])
            continue
        done += index_photo(row["id"], photo)
    log.info("AI 벡터를 %d개 만들었어요.", done)


def describe_item(item_id: int, photo_jpeg: bytes, memo: str | None) -> bool:
    """B 단계: Claude가 사진을 보고 특징을 정리해 저장한다. 실패해도 등록은 그대로 둔다."""
    if not describe.enabled():
        return False
    try:
        result = describe.describe_photo(photo_jpeg, memo)
        db.save_description(item_id, result.model_dump(), config.CLAUDE_MODEL)
        log.info("물건 %s번: Claude가 특징을 정리했어요 (%s).", item_id, result.category)
        return True
    except Exception:
        log.exception("물건 %s번: Claude 설명을 받지 못했어요. 서버를 다시 켜면 다시 시도해요.", item_id)
        return False


# 서버를 켤 때마다 Claude에게 보내는 최대 개수 (실수로 사용료가 많이 나오지 않게)
DESCRIBE_BACKFILL_LIMIT = 30


def backfill_descriptions() -> None:
    """Claude 설명이 없는 물건을 찾아 설명을 채운다."""
    if not describe.enabled():
        return
    missing = db.items_missing_description(DESCRIBE_BACKFILL_LIMIT)
    if not missing:
        return
    log.info("Claude 설명이 없는 물건 %d개를 처리할게요.", len(missing))
    done = 0
    for row in missing:
        try:
            photo = storage.load(row["photo_path"])
        except Exception:
            log.exception("물건 %s번의 사진을 읽지 못했어요.", row["id"])
            continue
        done += describe_item(row["id"], photo, row["memo"])
    log.info("Claude 설명을 %d개 만들었어요.", done)


def warm_up() -> None:
    """서버가 켜질 때 뒤에서 실행: AI 모델을 미리 불러오고, 빠진 벡터를 채운다."""
    try:
        embedding.get_model()
    except Exception:
        log.exception("AI 모델을 불러오지 못했어요. 인터넷 연결을 확인하고 서버를 다시 켜 주세요.")
        return
    try:
        backfill()
        backfill_descriptions()
    except Exception:
        log.exception("빠진 AI 벡터나 설명을 채우다가 오류가 났어요. 서버를 다시 켜면 다시 시도해요.")
