#!/usr/bin/env bash
# 우분투 서버(오라클 무료 서버 등)에 이 사이트를 설치하고, 서버 컴퓨터가 켜져 있는 동안 늘 돌아가게 만든다.
#
# 쓰는 법 (서버에서):   bash ~/youareliar/deploy/setup_server.sh
# 새 코드를 받을 때도:   cd ~/youareliar && git pull && bash deploy/setup_server.sh
# 여러 번 실행해도 괜찮다. 이미 된 단계는 금방 지나간다.
set -euo pipefail

cd "$(dirname "$0")/.."   # 저장소 맨 위 폴더로 간다
APP_DIR="$(pwd)"
APP_USER="$(whoami)"
SERVICE=lostfound          # 서버 프로그램 이름 (systemctl, journalctl에서 쓴다)
PORT=8000                  # 이 컴퓨터 안에서만 여는 문. 바깥 주소는 Tailscale이 만들어 준다.

# 0) 시작하기 전에 확인: 메모리와 .env
MEM_MB=$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 3500 ]; then
  echo "[멈춤] 이 서버의 메모리는 ${MEM_MB}MB예요. AI 모델에 약 3GB가 필요해서 4GB 이상이어야 해요."
  echo "       오라클에서 서버 모양(Shape)을 Ampere(VM.Standard.A1.Flex), 메모리 12GB로 만들어 주세요."
  exit 1
fi
if [ ! -f .env ]; then
  echo "[멈춤] .env 파일이 없어요. README의 '오라클 무료 서버에 올리기' 5번대로"
  echo "       노트북의 .env를 이 서버의 $APP_DIR 폴더로 복사한 뒤 다시 실행하세요."
  exit 1
fi
chmod 600 .env   # 비밀값이 들어 있으니 나만 읽을 수 있게

echo "[1/4] 필요한 프로그램 설치 (python, git)"
# 설치 중에 질문 창(서비스 다시 시작할지 등)이 떠서 멈추지 않게 한다
sudo apt-get update -qq
sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a apt-get install -y -qq python3 python3-venv git curl > /dev/null

echo "[2/4] 라이브러리 설치 (처음에는 10~20분 걸려요)"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
# torch는 그래픽카드(GPU)가 없는 서버용 가벼운 판을 먼저 받는다.
# 일반 판은 쓰지도 않을 GPU 프로그램 몇 GB를 같이 깐다. 못 받으면 일반 판으로 깔린다.
TORCH_PINS=$(grep -oE '^(torch|torchvision)==[^ #]+' requirements.txt)
# shellcheck disable=SC2086  # 'torch==… torchvision==…' 두 개로 나눠서 넘기려고 따옴표를 안 쓴다
.venv/bin/pip install --quiet $TORCH_PINS --index-url https://download.pytorch.org/whl/cpu \
  || echo "      (가벼운 torch를 못 받아서 일반 torch로 깔아요. 시간이 조금 더 걸려요.)"
.venv/bin/pip install --quiet -r requirements.txt

echo "[3/4] DB 표 준비"
.venv/bin/python -m app.migrate

echo "[4/4] 서버를 늘 켜 두는 설정 (멈추거나 컴퓨터가 다시 켜져도 알아서 다시 켠다)"
sudo tee /etc/systemd/system/$SERVICE.service > /dev/null <<EOF
[Unit]
Description=School lost-and-found AI search
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --quiet $SERVICE
sudo systemctl restart $SERVICE

# 서버가 대답하는지 확인한다(최대 1분). 첫 화면은 DB를 쓰니까, 200이면 DB 연결까지 된 것이다.
CODE=000
for _ in $(seq 30); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" || true)
  [ "$CODE" = 200 ] && break
  sleep 2
done

echo ""
if [ "$CODE" = 200 ]; then
  echo "다 됐어요! 서버가 켜졌어요. AI 모델은 뒤에서 불러오는 중이에요(처음에는 내려받느라 몇 분)."
else
  echo "[확인 필요] 서버가 아직 제대로 대답하지 않아요(응답 코드 $CODE). 아래 명령으로 서버 기록을 보세요."
fi
echo "  서버 기록 보기:   sudo journalctl -u $SERVICE -f     (그만 보려면 Ctrl+C)"
echo "  다음 할 일:       README의 '오라클 무료 서버에 올리기' 7번 (Tailscale로 사이트 주소 만들기)"
