"""사진과 문장을 '벡터'(숫자 목록)로 바꾸는 곳 — AI 검색의 핵심.

같은 AI 모델로 바꾼 벡터끼리는 같은 '의미 공간'에 놓인다.
그래서 두 벡터가 가까울수록(코사인 유사도가 클수록) 뜻이 비슷하다.

여기서는 모델 두 개를 쓴다.
1. 사진 검색 모델 (SigLIP 2, A 방식): 사진과 검색 문장을 같은 공간의 벡터로 바꾼다.
   예: "파란 텀블러" 문장 벡터는 파란 텀블러 '사진' 벡터와 가깝다.
2. 설명 검색 모델 (KURE-v1, B 방식): Claude가 쓴 설명과 검색 문장을 벡터로 바꾼다.
   한국어 글끼리 뜻을 비교하는 데 특화된 모델이다.
   예: "물 마시는 통" 문장 벡터는 "텀블러" 설명 벡터와 가깝다(단어가 달라도).

모델은 처음 쓸 때 한 번만 불러온다. 맨 처음에는 인터넷에서 내려받는다(각각 약 1.5GB, 2.3GB).
"""
import logging
import threading

import numpy as np
from PIL import Image

from . import config

log = logging.getLogger("uvicorn.error")


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


class KureText:
    """KURE-v1 모델(고려대 NLP 연구실). 한국어 글을 검색용 벡터로 바꾼다."""

    def __init__(self, model_id: str):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.model = AutoModel.from_pretrained(model_id).eval()
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        with self.torch.no_grad():
            inputs = self.tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt")
            # 이 모델은 문장 맨 앞 칸([CLS])의 결과를 그 문장 전체의 뜻으로 쓴다.
            output = self.model(**inputs).last_hidden_state[:, 0]
        return _normalize(output)


def _normalize(output) -> np.ndarray:
    """벡터 길이를 1로 맞춘다. 그러면 두 벡터의 곱(내적)이 곧 코사인 유사도가 된다."""
    tensor = getattr(output, "pooler_output", output)  # 라이브러리 버전에 따라 한 번 감싸서 줄 때가 있다
    vectors = tensor.float().cpu().numpy()
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


class _LazyModel:
    """처음 쓸 때 한 번만 불러오는 모델 상자. 여러 요청이 동시에 와도 한 번만 불러온다."""

    def __init__(self, label: str, factory):
        self.label = label
        self.factory = factory
        self.model = None
        self.status = "idle"  # idle(아직 안 부름) → loading(불러오는 중) → ready(준비됨) / error(실패)
        self.lock = threading.Lock()

    def get(self):
        if self.model is None:
            with self.lock:
                if self.model is None:
                    self.status = "loading"
                    log.info("%s을 불러오는 중… 처음에는 내려받느라 몇 분 걸릴 수 있어요.", self.label)
                    try:
                        model = self.factory()
                        # 준비 운동: AI 모델은 첫 계산 때 준비 작업을 하느라 오래 걸린다.
                        # 서버가 켜질 때 미리 한 번 계산해 두면, 첫 번째 검색하는 사람이 기다리지 않는다.
                        model.embed_texts(["준비 운동"])
                    except Exception:
                        self.status = "error"
                        raise
                    self.model = model
                    self.status = "ready"
                    log.info("%s을 다 불러왔어요.", self.label)
        return self.model


_image_model = _LazyModel(
    f"AI 모델({config.EMBED_MODEL})", lambda: SigLIP2(config.EMBED_MODELS[config.EMBED_MODEL])
)
_text_model = _LazyModel(
    f"설명 검색 모델({config.TEXT_EMBED_MODEL})",
    lambda: KureText(config.TEXT_EMBED_MODELS[config.TEXT_EMBED_MODEL]),
)


# ---------- 사진 검색 모델 (A) ----------


def get_model() -> SigLIP2:
    return _image_model.get()


def status() -> str:
    """사진 검색 모델 상태: 'idle', 'loading', 'ready', 'error' 중 하나."""
    return _image_model.status


def embed_image(image: Image.Image) -> np.ndarray:
    """사진 한 장 → 벡터 하나."""
    return get_model().embed_images([image.convert("RGB")])[0]


def embed_text(text: str) -> np.ndarray:
    """검색 문장 → 사진과 비교할 벡터 하나."""
    return get_model().embed_texts([text])[0]


# ---------- 설명 검색 모델 (B) ----------


def get_text_model() -> KureText:
    return _text_model.get()


def text_status() -> str:
    """설명 검색 모델 상태: 'idle', 'loading', 'ready', 'error' 중 하나."""
    return _text_model.status


def embed_description(text: str) -> np.ndarray:
    """설명 글 또는 검색 문장 → 설명끼리 비교할 벡터 하나."""
    return get_text_model().embed_texts([text])[0]
