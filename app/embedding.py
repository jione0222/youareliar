"""사진과 문장을 '벡터'(숫자 목록)로 바꾸는 곳 — A 검색의 핵심.

같은 AI 모델로 바꾼 사진 벡터와 문장 벡터는 같은 '의미 공간'에 놓인다.
그래서 두 벡터가 가까울수록(코사인 유사도가 클수록) 사진과 문장의 뜻이 비슷하다.
예: "파란 텀블러"라는 문장 벡터는 파란 텀블러 사진 벡터와 가깝고, 체육복 사진 벡터와는 멀다.

모델은 .env의 EMBED_MODEL로 고른다(쓸 수 있는 모델 목록은 config.py의 EMBED_MODELS).
모델은 처음 쓸 때 한 번만 불러온다. 맨 처음에는 인터넷에서 약 1.5GB를 내려받는다.
"""
import logging
import threading

import numpy as np
from PIL import Image

from . import config

log = logging.getLogger("uvicorn.error")

_model = None
_lock = threading.Lock()
_status = "idle"  # idle(아직 안 부름) → loading(불러오는 중) → ready(준비됨) / error(실패)


class SigLIP2:
    """구글 SigLIP 2 모델. 사진과 여러 언어 문장을 같은 공간의 벡터로 바꾼다."""

    def __init__(self, model_id: str):
        import torch
        from transformers import AutoModel, AutoProcessor

        self.torch = torch
        self.model = AutoModel.from_pretrained(model_id).eval()  # eval(): 학습이 아니라 사용 모드
        self.processor = AutoProcessor.from_pretrained(model_id)

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        with self.torch.no_grad():  # 사용만 할 때는 학습용 계산 기록을 끈다(빠르고 메모리 절약)
            inputs = self.processor(images=images, return_tensors="pt")
            output = self.model.get_image_features(**inputs)
        return _normalize(output)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        with self.torch.no_grad():
            # SigLIP은 문장을 64토큰 길이로 맞춰서 학습했기 때문에 똑같이 맞춰 준다.
            inputs = self.processor(
                text=texts, padding="max_length", max_length=64, truncation=True, return_tensors="pt"
            )
            output = self.model.get_text_features(**inputs)
        return _normalize(output)


def _normalize(output) -> np.ndarray:
    """벡터 길이를 1로 맞춘다. 그러면 두 벡터의 곱(내적)이 곧 코사인 유사도가 된다."""
    tensor = getattr(output, "pooler_output", output)  # 라이브러리 버전에 따라 한 번 감싸서 줄 때가 있다
    vectors = tensor.float().cpu().numpy()
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def get_model() -> SigLIP2:
    """모델을 (처음 한 번만) 불러와서 돌려준다. 여러 요청이 동시에 와도 한 번만 불러온다."""
    global _model, _status
    if _model is None:
        with _lock:
            if _model is None:
                _status = "loading"
                log.info("AI 모델(%s)을 불러오는 중… 처음에는 내려받느라 몇 분 걸릴 수 있어요.", config.EMBED_MODEL)
                try:
                    _model = SigLIP2(config.EMBED_MODELS[config.EMBED_MODEL])
                except Exception:
                    _status = "error"
                    raise
                _status = "ready"
                log.info("AI 모델을 다 불러왔어요.")
    return _model


def status() -> str:
    """'idle', 'loading', 'ready', 'error' 중 하나."""
    return _status


def embed_image(image: Image.Image) -> np.ndarray:
    """사진 한 장 → 벡터 하나."""
    return get_model().embed_images([image.convert("RGB")])[0]


def embed_text(text: str) -> np.ndarray:
    """문장 하나 → 벡터 하나."""
    return get_model().embed_texts([text])[0]
