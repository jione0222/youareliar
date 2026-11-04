# 학교 분실물 AI 찾기

학교에서 주운 물건을 사진으로 올려 두면, 잃어버린 사람이 물건 특징을 문장으로 검색해서 찾을 수 있게 돕는 웹사이트입니다.

## 지금 되는 것 (1단계)
- **주운 물건 등록**: 휴대폰 카메라로 바로 찍거나 앨범에서 골라 올립니다. 보관 장소(필수), 발견 장소, 발견 날짜, 메모를 함께 적습니다.
- **목록과 상세 화면**: 최근 등록 순으로 보여 주고, 누르면 보관 장소를 크게 보여 줍니다.
- **사진 처리**: 휴대폰 사진을 작게 줄이고(목록용·상세용), 옆으로 누운 사진을 바로 세우고, 찍은 위치(GPS) 같은 숨은 정보를 지웁니다.

## 앞으로 만들 것
1. A 검색: 사진과 검색 문장을 벡터로 바꿔 비슷한 순서로 보여 주기
2. B: Claude가 사진을 보고 물건 설명 정리하기
3. 재순위: Claude가 상위 후보를 다시 줄 세우고, 비슷한 이유 보여 주기
4. 관리자 기능(숨기기, 주인 찾음 표시), 사진 속 이름·얼굴 가리기

## 폴더 구조
```
app/
  main.py        서버의 시작점. 주소(URL)마다 어떤 화면을 보여 줄지 정한다
  config.py      .env 파일에서 설정값을 읽는다
  db.py          DB에 저장하고 꺼내는 SQL을 모아 둔 곳
  storage.py     사진 파일 저장 (Supabase Storage, 또는 연습용 uploads 폴더)
  images.py      사진 줄이기, 회전 바로잡기, 숨은 정보 지우기
  migrate.py     DB 표와 사진 저장 공간을 준비하는 스크립트
  templates/     화면(HTML)
  static/        화면 꾸미기(CSS)
db/migrations/   DB 구조를 바꾼 기록(SQL 파일, 번호 순서대로 적용)
```

## 처음 한 번 설정하기

### 1. 준비물
- **Python 3.11 이상** (3.12나 3.13 권장): [python.org](https://www.python.org/downloads/)에서 설치합니다. 윈도우에서는 설치 첫 화면에서 **"Add python.exe to PATH"를 꼭 체크**하세요.
- 이 저장소를 내 컴퓨터로 받아 둡니다(`git clone`).

### 2. 라이브러리 설치
프로젝트 폴더에서 아래 명령을 차례로 실행합니다. `.venv`는 이 프로젝트 전용 파이썬 환경(가상환경)입니다.

**Mac**
```bash
python3 -m venv .venv
```
```bash
source .venv/bin/activate
```
```bash
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
py -m venv .venv
```
```powershell
.venv\Scripts\Activate.ps1
```
```powershell
pip install -r requirements.txt
```
`Activate.ps1`에서 "스크립트를 실행할 수 없습니다" 오류가 나면, 아래 명령을 한 번 실행한 뒤 다시 해 보세요.
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

> 새 터미널을 열 때마다 `activate` 명령을 다시 실행해야 합니다. 터미널 맨 앞에 `(.venv)`가 보이면 켜진 상태입니다.

### 3. Supabase 프로젝트 만들기 (팀에서 한 명만)
1. [supabase.com](https://supabase.com)에 가입합니다(GitHub 계정으로 가입 가능). **New project**를 누릅니다.
2. Region은 **Northeast Asia (Seoul)** 을 고릅니다. Database Password를 정하고 따로 적어 둡니다.
3. 프로젝트가 만들어지면 아래 세 가지 값을 복사합니다.
   - `DATABASE_URL`: 대시보드 위쪽 **Connect** 버튼 → **Session pooler** 연결 문자열. `[YOUR-PASSWORD]` 자리에 2번에서 정한 DB 비밀번호를 넣습니다.
   - `SUPABASE_URL`: `https://프로젝트ID.supabase.co` 형태의 주소입니다. 프로젝트 설정 화면에서 볼 수 있습니다.
   - `SUPABASE_SECRET_KEY`: **Project Settings → API Keys** 의 Secret key입니다(`sb_secret_`로 시작).
4. DB 비밀번호와 비밀 키는 단체 채팅방이나 깃에 올리지 말고, 팀원에게 직접 전달하세요. 이 키가 있으면 누구나 DB를 지우거나 바꿀 수 있습니다.

### 4. `.env` 파일 만들기
`.env.example`을 복사해서 `.env`라는 이름으로 저장하고, 3번에서 복사한 값을 채웁니다.

Mac:
```bash
cp .env.example .env
```
Windows:
```powershell
copy .env.example .env
```

### 5. DB 표와 사진 저장 공간 만들기
```bash
python -m app.migrate
```
마지막에 `준비 완료!`가 나오면 성공입니다. 여러 번 실행해도 괜찮습니다(이미 한 것은 건너뜁니다).

## 실행하기
```bash
uvicorn app.main:app --reload
```
브라우저에서 http://localhost:8000 을 엽니다. `--reload`를 붙이면 코드를 고칠 때마다 서버가 저절로 다시 켜집니다. 끌 때는 터미널에서 `Ctrl + C`를 누릅니다.

## 휴대폰으로 접속하기 (같은 와이파이)
1. 서버를 이렇게 켭니다(같은 와이파이의 다른 기기도 들어올 수 있게).
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0
   ```
2. 컴퓨터의 IP 주소를 확인합니다.
   - Windows: PowerShell에서 `ipconfig` → "IPv4 주소" (예: `192.168.0.12`)
   - Mac: 시스템 설정 → Wi-Fi → 연결된 와이파이의 **세부사항** → IP 주소
3. 휴대폰 브라우저에서 `http://192.168.0.12:8000` 처럼 엽니다.
4. 윈도우에서 방화벽 허용 창이 뜨면 **허용**을 누릅니다.
5. 그래도 안 되면: 학교 와이파이는 기기끼리 연결하는 것을 막아 둔 경우가 많습니다. 휴대폰 핫스팟을 켜고 컴퓨터를 그 핫스팟에 연결해서 해 보세요.

## 직접 확인해 볼 것
- [ ] 휴대폰에서 **카메라로 찍기** → 찍고 등록 → 상세 화면에 "등록됐어요" 메시지가 나온다
- [ ] 목록 맨 앞에 방금 등록한 물건이 나온다
- [ ] 휴대폰을 세로로, 가로로 들고 찍은 사진이 모두 똑바로 보인다
- [ ] Supabase 대시보드의 **Table Editor → items** 에 줄이 생기고, **Storage → photos** 에 사진이 생긴다

## 문제가 생겼을 때
- `DATABASE_URL이 없습니다` → `.env` 파일이 프로젝트 폴더 맨 위에 있는지, 이름이 정확히 `.env`인지 확인하세요.
- `password authentication failed` → `DATABASE_URL`의 비밀번호를 확인하세요. 대괄호 `[ ]`까지 지우고 비밀번호만 넣어야 합니다.
- 사진 저장에서 `JWT`나 `Invalid API key` 오류 → Supabase의 **API Keys** 화면에 있는 Legacy API keys 탭의 `service_role` 키를 `SUPABASE_SECRET_KEY`에 넣어 보세요.

## 알아 둘 점
- **비밀값은 `.env`에만** 넣습니다. `.env`는 `.gitignore`에 등록돼 있어 깃에 올라가지 않습니다.
- Supabase 무료 요금제는 **7일 동안 아무도 쓰지 않으면 프로젝트가 일시정지**됩니다. 대시보드에서 다시 켜면 데이터는 그대로 있습니다.
- **연습 모드**: `.env`에서 `SUPABASE_URL`을 비워 두면 사진을 이 컴퓨터의 `uploads` 폴더에 저장합니다. 이때도 Postgres DB는 필요합니다.
