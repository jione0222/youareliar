# Google Cloud Run에 올릴 서버 이미지를 만드는 설명서.
# 구글(Cloud Build)이 깃허브의 이 파일을 읽어서 이미지를 만들고, Cloud Run이 그 이미지로 서버를 켠다.
# 공식 파이썬 이미지를 구글의 복사본(mirror.gcr.io)에서 받는다. Docker Hub가 요청이 많다고 막는 일을 피하려는 것이다.
FROM mirror.gcr.io/library/python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    OMP_NUM_THREADS=2

WORKDIR /app

# 1) 라이브러리 설치.
#    torch는 그래픽카드(GPU)가 없는 서버용 가벼운 판을 먼저 깐다. 일반 판은 쓰지 않을 GPU 프로그램 몇 GB를 같이 깐다.
#    버전은 requirements.txt에 적힌 것을 그대로 쓴다.
COPY requirements.txt .
RUN pip install $(grep -oE '^(torch|torchvision)==[^ #]+' requirements.txt) \
        --index-url https://download.pytorch.org/whl/cpu \
    || echo "가벼운 torch를 못 받아서 일반 torch로 깐다"; \
    pip install -r requirements.txt

# 2) AI 모델을 이미지 안에 미리 받아 둔다. 서버가 켜질 때마다 3.6GB를 내려받지 않게 하려는 것이다.
#    모델 이름은 app/config.py의 EMBED_MODELS, TEXT_EMBED_MODELS와 같아야 한다.
RUN python -c "from huggingface_hub import snapshot_download as d; [d(m, allow_patterns=['*.json', 'model.safetensors']) for m in ('google/siglip2-base-patch16-256', 'nlpai-lab/KURE-v1')]"
# 받아 둔 모델만 쓰고, 서버가 켜질 때 인터넷에서 다시 확인하지 않는다.
ENV HF_HUB_OFFLINE=1

# 3) 우리 코드
COPY . .

# Cloud Run이 정해 주는 포트(PORT, 보통 8080)로 서버를 켠다.
# --proxy-headers: 구글 앞단이 알려 주는 'https로 들어왔다'는 정보를 믿는다(로그인 쿠키에 필요).
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips '*'"]
