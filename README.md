# 학교 분실물 AI 찾기

학교에서 주운 물건을 사진으로 올려 두면, 잃어버린 사람이 물건 특징을 문장으로 검색해서 찾을 수 있게 돕는 웹사이트입니다.

## 지금 되는 것
- **주운 물건 등록**: 휴대폰 카메라로 바로 찍거나 앨범에서 골라 올립니다. 보관 장소(필수), 발견 장소, 발견 날짜, 메모를 함께 적습니다.
- **목록과 상세 화면**: 최근 등록 순으로 보여 주고, 누르면 보관 장소를 크게 보여 줍니다.
- **사진 처리**: 휴대폰 사진을 작게 줄이고(목록용·상세용), 옆으로 누운 사진을 바로 세우고, 찍은 위치(GPS) 같은 숨은 정보를 지웁니다.
- **AI 검색**: "파란 텀블러, 고양이 스티커"처럼 문장으로 검색하면 비슷한 물건부터 순위대로 보여 줍니다. 세 가지 방법으로 찾은 순위를 합쳐요(`app/search.py`).
  1. **사진 벡터 (A 방식)**: 구글 **SigLIP 2** 모델이 사진과 검색 문장을 숫자 768개짜리 '벡터'로 바꿉니다. 뜻이 비슷하면 벡터도 가까워요.
  2. **설명 벡터 (B 방식)**: 한국어 특화 모델 **KURE-v1**이 Claude가 쓴 설명과 검색 문장을 벡터로 바꿉니다. "물 마시는 통"처럼 단어가 달라도 "텀블러" 설명을 찾아요.
  3. **키워드**: 검색 문장을 두 글자씩 쪼개서 설명·메모·장소에 얼마나 들어 있는지 봅니다. '노스페이스' 같은 고유한 이름을 잘 잡아요.
  - 합치는 법(RRF): 방법마다 받은 등수로 점수를 주고(1등일수록 큼) 더합니다. 비중은 사진 1 : 설명 1 : 키워드 0.5예요.
  - 벡터는 등록할 때 만들어 DB(`item_vectors` 표)에 저장하고, 검색할 때 pgvector의 코사인 거리로 가까운 것부터 찾습니다.
  - 서버를 켜면 뒤에서 AI 모델을 불러오고, 벡터가 빠진 물건이 있으면 자동으로 채웁니다.
  - **재순위 (Claude 키가 있을 때)**: 결과를 먼저 보여 준 뒤, Claude가 상위 10개 후보를 검색 문장과 하나씩 다시 비교해요. 몇 초 뒤 순서가 바뀌고, 카드마다 '같은 물건일 가능성 높음/비슷함/다른 물건 같음'과 한 문장 이유가 붙어요(`app/rerank.py`).
    - 같은 검색은 30분 동안 기억해 둬서 Claude를 다시 부르지 않아요. 하루에 부르는 횟수는 `RERANK_DAILY_LIMIT`(기본 200번)까지예요.
    - 재순위만 더 싸고 빠른 모델로 돌리고 싶으면 `.env`의 `CLAUDE_RERANK_MODEL`에 적어요.
  - 검색 주소 끝에 `&debug=1`을 붙이면 카드마다 "사진 2등 · 설명 1등 · 키워드 3등"처럼 방법별 등수가 보여요. 발표나 정확도 시험 때 쓰세요.
- **Claude가 사진 정리하기 (B 방식, Claude API 키가 있을 때만)**: 등록하면 Claude가 사진을 보고 종류·색·브랜드·특징(스티커, 흠집 등)·검색어를 정리합니다.
  - 상세 화면의 **'AI가 본 특징'**에 보이고, 목록 카드에는 물건 종류가 나옵니다.
  - 사진에 **사람 얼굴이나 이름·학번 같은 개인정보**가 보이면 관리자 화면에 '개인정보 의심'으로 알려 줘요. `.env`에서 `HIDE_PRIVATE_PHOTOS=true`로 켜면 관리자가 확인하기 전까지 공개 화면에서 사진을 가려요(지금은 팀이 꺼 두기로 했어요).
  - 등록 화면은 바로 넘어가고, Claude 정리는 뒤에서 몇 초 안에 끝납니다(상세 화면을 새로고침하면 보여요).
  - 서버를 켤 때 아직 정리되지 않은 물건이 있으면 자동으로 정리합니다(한 번에 최대 30개, 사용료가 갑자기 많이 나오지 않게).

- **회원가입·로그인**: 아이디·닉네임·비밀번호로 가입하고 로그인해요. 학교 인증이나 이메일 인증은 아직 없어요. 로그인하지 않아도 사이트는 그대로 쓸 수 있고, 로그인한 채로 등록하면 누가 등록했는지 기록돼요.
  - 비밀번호는 원래 글자가 아니라 되돌릴 수 없게 바꾼 값(scrypt 해시)으로 저장해요.
  - 로그인하면 무작위 '로그인 표시'(쿠키)를 주고, DB에는 그 해시만 적어 둬요. 로그아웃하면 DB에서 지워서 같은 표시로 다시 들어올 수 없어요.
- **관리자 화면 (`/admin`)**: 비밀번호를 아는 사람만 들어올 수 있어요. 장난 글 숨기기·지우기, '주인 찾음' 표시, 개인정보 때문에 가린 사진 확인을 할 수 있어요.

## 앞으로 할 것
1. 실제 물건 사진을 모아서 정확도 시험 돌리기 (아래 '정확도 시험')
2. 오라클 무료 서버에 올려서 늘 켜 두기 (아래 '오라클 무료 서버에 올리기')

## 폴더 구조
```
app/
  main.py        서버의 시작점. 주소(URL)마다 어떤 화면을 보여 줄지 정한다
  config.py      .env 파일에서 설정값을 읽는다
  db.py          DB에 저장하고 꺼내는 SQL을 모아 둔 곳
  storage.py     사진 파일 저장 (Supabase Storage, 또는 연습용 uploads 폴더)
  images.py      사진 줄이기, 회전 바로잡기, 숨은 정보 지우기
  embedding.py   AI 모델로 사진·문장(SigLIP 2), 설명·문장(KURE-v1)을 벡터로 바꾸기
  search.py      AI 검색: 사진 벡터·설명 벡터·키워드 순위를 합치기(RRF)
  rerank.py      재순위: Claude가 상위 후보를 다시 줄 세우고 이유 쓰기
  evaluate.py    정확도 시험: 검색 방법별 정답률 재기
  indexing.py    등록할 때 벡터 만들기·Claude 정리 맡기기, 빠진 것 채우기
  describe.py    Claude API로 사진을 보고 특징 정리하기 (B 방식)
  admin.py       관리자 화면: 로그인, 숨기기·지우기·주인 찾음·사진 확인
  auth.py        회원 기능의 바탕: 비밀번호 해시, 로그인 상태 확인
  accounts.py    회원가입·로그인·로그아웃 화면
  templating.py  화면(HTML 템플릿) 공통 설정
  migrate.py     DB 표와 사진 저장 공간을 준비하는 스크립트
  templates/     화면(HTML)
  static/        화면 꾸미기(CSS)
db/migrations/   DB 구조를 바꾼 기록(SQL 파일, 번호 순서대로 적용)
eval/            정확도 시험 자료 (photos/ 사진, queries.csv 표)
deploy/          서버에 올리기: setup_server.sh (우분투 서버에 설치하고 늘 켜 두기)
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

- **처음 켤 때는 AI 모델(약 1.5GB)을 인터넷에서 내려받느라 몇 분 걸립니다.** 서버 창에 `AI 모델을 다 불러왔어요.`가 나온 뒤부터 검색할 수 있어요. 그 전에 검색하면 "AI 모델을 준비하고 있어요" 안내가 나옵니다.
- 두 번째부터는 내려받은 모델을 쓰므로 10~30초면 준비됩니다.
- Claude 기능을 쓰면 설명 검색 모델(KURE-v1, 약 2.3GB)도 내려받아요. 서버 창에 `설명 검색 모델(kure-v1)을 다 불러왔어요.`가 나오면 준비 끝이에요. 두 모델을 합쳐 메모리를 약 3GB 씁니다.
- 윈도우에서 서버 창 안을 마우스로 클릭하면 창 이름 앞에 '선택'이 붙으면서 서버가 멈춥니다. 그럴 땐 그 창에서 `Esc`를 누르세요.

## Claude 기능 켜기 (B 방식)
1. Claude 콘솔(platform.claude.com)에서 API 키를 만듭니다. 결제 등록이 필요하니 **월 사용 한도**도 꼭 걸어 두세요.
2. `.env`에 두 줄을 채웁니다.
   - `ANTHROPIC_API_KEY=` 뒤에 만든 키(`sk-ant-`로 시작)
   - `CLAUDE_MODEL=` 뒤에 쓸 Claude 모델 이름(Claude 문서의 모델 목록에서 고릅니다. 팀은 상위 모델과 저가 모델을 시험해서 정해요)
3. 서버를 다시 켭니다. 서버 창에 `Claude가 특징을 정리했어요`가 나오면 동작하는 거예요.
- 물건을 등록할 때마다 Claude를 한 번 부르고, 그때마다 사용료가 조금씩 나갑니다. 서버 창에 쓴 토큰 수가 찍혀요.
- 두 줄을 비워 두면 Claude 기능만 꺼지고, 등록과 A 검색은 그대로 됩니다.

## 관리자 화면 쓰기
1. `.env`의 `ADMIN_PASSWORD=` 뒤에 **8자 이상**의 비밀번호를 정해 넣고 서버를 다시 켭니다. 선생님과 운영 팀만 알게 하세요.
2. 사이트 맨 아래의 **관리자** 링크를 누르거나 `/admin` 주소로 들어가 비밀번호를 넣습니다. 한 번 들어가면 그 브라우저에서 7일 동안 유지돼요.
3. 할 수 있는 일
   - **주인 찾음으로 / 보관 중으로**: 물건을 돌려준 뒤 표시를 바꿉니다.
   - **숨기기 / 다시 보이기**: 장난 글을 공개 화면(목록, 검색, 상세)에서 숨깁니다. 지우지는 않아요.
   - **확인 완료**: Claude가 얼굴이나 개인정보가 있다고 본 사진은 **사진 확인 필요** 탭에 모여요. 관리자가 직접 보고 문제없으면 확인 완료, 문제 있으면 숨기기를 누르세요. (`HIDE_PRIVATE_PHOTOS=true`일 때는 확인 완료를 눌러야 공개 화면에 사진이 보여요.)
   - **지우기**: 글과 사진 파일을 완전히 지웁니다. 되돌릴 수 없어요.

## 정확도 시험 (개발 순서 3단계)
'단순 키워드 검색 / A / B / A+B / 재순위까지'가 정답을 몇 등에 찾는지 비교해요. 대회 발표에서 "AI를 쓰면 얼마나 더 잘 찾는지" 보여 주는 근거예요.

### 1. 자료 준비
1. 물건 사진을 `eval/photos/` 폴더에 `01.jpg`, `02.jpg`처럼 번호로 저장해요(물건 하나에 한 장, 30~50개 추천).
2. 구글 시트에 칸 세 개를 만들어요. `eval/queries.example.csv`가 예시예요.

   | 사진 | 메모 | 검색 문장 |
   |---|---|---|
   | 01.jpg | 파란 텀블러 | 파란 텀블러 잃어버렸어요 뚜껑에 고양이 스티커 있어요 |
   | 01.jpg | | 물 마시는 파란 통 검은 뚜껑 |

   - **메모**: 물건을 주운 사람이 등록할 때 쓸 법한 짧은 설명이에요. AI 없는 '단순 키워드 검색'은 이것만 보고 찾아요. 사진마다 첫 줄에 한 번만 써도 돼요.
   - **검색 문장**: 물건 **주인이 사진을 보지 않고**, 잃어버렸다고 생각하며 쓴 문장이에요. 물건마다 2~3줄 써 주세요.
3. 구글 시트에서 **파일 → 다운로드 → CSV**로 받아, 이름을 `queries.csv`로 바꿔 `eval/` 폴더에 넣어요(한국어 엑셀에서 저장한 CSV도 괜찮아요).

### 2. 실행
```bash
python -m app.evaluate
```
- 시작하기 전에 Claude를 몇 번 부를지(사용료)를 알려 주고 물어봐요. `y`를 누르면 진행해요.
- Claude 없이 '단순 키워드 vs A'만 먼저 보고 싶으면:
  ```bash
  python -m app.evaluate --no-claude
  ```
- Claude의 답은 `eval/cache/`에 저장해 두고 다시 써서, 같은 자료로 다시 돌리면 사용료가 거의 들지 않아요.

### 3. 결과 보기
- 화면에 방법별 **1등 정답률, 5등 안 정답률, MRR**(정답이 1등이면 1점, 2등이면 0.5점…의 평균) 표가 나와요.
- **합치는 비중 찾아보기**: 사진·키워드를 어떤 비중으로 섞을 때 가장 잘 맞는지 보여 줘요. 지금 설정(사진 1, 키워드 0.5)보다 좋은 조합이 있으면 알려 주세요.
- `eval/results/`에 마크다운(발표용 표)과 CSV(엑셀용)로 저장돼요. 검색 문장마다 각 방법이 정답을 몇 등에 찾았는지도 들어 있어요.

### 4. Claude 모델 비교
`.env`의 `CLAUDE_MODEL`(재순위만 바꾸려면 `CLAUDE_RERANK_MODEL`)을 다른 모델로 바꾸고 한 번 더 돌려요. 결과 파일에 어떤 모델로 돌렸는지 적혀 있어요.

## 운영 모드로 계속 켜 두기 (윈도우)
개발할 때는 `uvicorn ... --reload`로 켜지만, 사이트를 계속 열어 둘 때는 프로젝트 폴더의 **`start_server.bat`**을 더블클릭하세요.
- 코드가 바뀌었는지 살피지 않는 '운영 모드'로 켜고, 서버가 멈추면 10초 뒤 **알아서 다시 켜요.**
- 서버 기록은 `logs\server.log`에 저장돼요(메모장으로 열기). 창 안을 클릭해도 서버가 멈추지 않아요.
- 끌 때는 그 창을 닫으면 돼요.
- 인터넷에 계속 열어 두면 장난으로 Claude 사용료를 써 버릴 수 있어서, 하루 한도가 있어요: 사진 정리 `DESCRIBE_DAILY_LIMIT`(기본 100번), 재순위 `RERANK_DAILY_LIMIT`(기본 200번). 한도를 넘은 사진은 다음 날 자동으로 이어서 정리해요.
- 서버를 켜 둔 동안 30분마다 빠진 벡터·설명을 다시 확인해서 채워요.

## 오라클 무료 서버에 올리기 (내 컴퓨터를 꺼도 되는 방법)
오라클이 무료로 빌려주는 서버(인터넷에 늘 켜져 있는 컴퓨터)에 사이트를 올립니다. 데이터는 지금처럼 Supabase에 있고 서버는 계산만 해서, 서버에 문제가 생겨도 데이터는 안전해요. 새 서버를 만들어 다시 설치하면 돼요.

순서: 가입 → 서버 만들기 → 접속 → 코드 받기 → `.env` 복사 → 설치 → 사이트 주소 만들기

### 1. 오라클 가입 (팀에서 한 명)
- https://signup.cloud.oracle.com 에서 가입합니다.
- **Home Region(홈 영역)은 `Japan Central (Osaka)`** 를 고르세요. 없으면 `Japan East (Tokyo)`를 고르세요.
  - 한국(서울)은 새로 가입할 때 고를 수 없어요. 춘천이 보여도 고르지 마세요. 춘천에서는 무료 ARM 서버(A1)를 만들 수 없어요.
  - 일본은 Supabase(서울)와 가까워서, 서버가 DB에 한 번 다녀오는 데 0.03초 정도만 더 걸려요.
  - 홈 영역은 나중에 바꿀 수 없고, 무료 서버는 이 지역에만 만들 수 있어요.
- 휴대폰 인증과 **카드 본인 확인**이 있어요. 확인용으로 잠깐 결제됐다가 취소되고, 무료 한도 안에서는 돈이 나가지 않아요. 카드 주인(예: 부모님)과 함께 가입하세요.

### 2. 서버 만들기
1. 왼쪽 위 메뉴 → **Compute → Instances → Create instance**
2. **Name**: `lostfound`
3. **Image**: Change image → **Canonical Ubuntu 24.04**
4. **Shape**: Change shape → **Ampere → VM.Standard.A1.Flex** → OCPU **2**, Memory **12** GB ("Always Free-eligible" 표시를 확인)
   - 처음 골라져 있는 `VM.Standard.E2.1.Micro`(메모리 1GB)로는 AI 모델이 안 돌아가요. 꼭 바꾸세요.
   - 왜 12GB인가요: 오라클은 7일 동안 CPU·네트워크·메모리를 모두 20%보다 적게 쓰는 무료 서버를 '노는 서버'로 보고 회수할 수 있어요. 우리 서버는 메모리를 3GB 넘게 써서 12GB의 25~30%가 돼요. 24GB로 만들면 20%가 안 돼서 회수될 수 있어요.
5. **Networking**: 그대로 두고, `Assign a public IPv4 address`가 켜져 있는지만 확인
6. **Add SSH keys**: `Generate a key pair for me` → **Download private key**. 이 파일이 서버 열쇠예요. 잃어버리면 접속할 수 없어요.
7. **Create**. `Out of capacity`(자리 없음)가 나오면 몇 시간 뒤 다시 하거나, OCPU 1·메모리 6GB로 해 보세요.
8. 상태가 **Running**이 되면 **Public IP address**(예: `152.70.12.34`)를 적어 둡니다.

### 3. 노트북에서 서버에 접속하기 (PowerShell)
열쇠 파일을 정해진 곳으로 옮깁니다(파일 이름은 받은 이름으로 바꾸세요).
```powershell
mkdir $HOME\.ssh -Force
```
```powershell
Move-Item $HOME\Downloads\ssh-key-2026-11-08.key $HOME\.ssh\oracle.key
```
접속합니다(`공인IP` 자리에 2-8의 주소).
```powershell
ssh -i $HOME\.ssh\oracle.key ubuntu@공인IP
```
- 처음에 `Are you sure you want to continue connecting`이 나오면 `yes`
- 줄 맨 앞이 `ubuntu@lostfound:~$`로 바뀌면 서버 안이에요. 이제부터 치는 명령은 서버에서 실행돼요. 나올 때는 `exit`.
- `UNPROTECTED PRIVATE KEY FILE` 또는 `bad permissions` 오류가 나면, 아래를 한 번 실행하고 다시 접속하세요.
  ```powershell
  icacls $HOME\.ssh\oracle.key /inheritance:r /grant:r "$($env:USERNAME):(R)"
  ```

### 4. 서버에 코드 받기 (서버에서)
```bash
git clone https://github.com/jione0222/youareliar.git
```

### 5. `.env` 복사하기 (노트북에서)
`.env`는 깃에 없어서 직접 옮겨야 해요. **새 PowerShell 창**을 열고 프로젝트 폴더로 간 뒤:
```powershell
scp -i $HOME\.ssh\oracle.key .env ubuntu@공인IP:~/youareliar/.env
```
노트북에서 잘 되던 `.env`를 그대로 쓰면 돼요.

### 6. 설치하기 (서버에서)
```bash
bash ~/youareliar/deploy/setup_server.sh
```
- 처음에는 10~20분 걸려요. 마지막에 `다 됐어요!`가 나오면 성공이에요.
- 서버 기록 보기: `sudo journalctl -u lostfound -f` → `DB에 연결했어요.`와 `AI 모델(...)을 다 불러왔어요.`가 보이면 준비 끝(처음에는 모델을 내려받느라 몇 분). 그만 보려면 Ctrl+C.
- 이제 서버 컴퓨터가 다시 켜지거나 서버가 멈춰도 알아서 다시 켜져요.

### 7. 사이트 주소 만들기 (Tailscale, 서버에서)
Tailscale이 `https://lostfound.xxxx.ts.net` 같은 무료 고정 주소를 만들어 줘요. 서버의 문(포트)을 따로 열지 않아도 돼요.
```bash
curl -fsSL https://tailscale.com/install.sh | sh
```
```bash
sudo tailscale up --hostname lostfound
```
나오는 주소를 노트북 브라우저에서 열고 로그인(구글 계정 등) → **Connect**.
```bash
sudo tailscale funnel --bg 8000
```
- 처음에는 `Funnel is not enabled`와 함께 주소가 나와요. 그 주소를 열어 **Enable**을 누르고, 같은 명령을 다시 실행하세요.
- `Available on the internet:` 아래의 `https://...ts.net/`이 사이트 주소예요. 휴대폰으로 열어 보세요(처음에는 몇 초 걸릴 수 있어요).
- 서버를 다시 켜도 주소는 그대로예요.

### 8. 다 됐으면
- 노트북 서버는 꺼도 돼요. 둘 다 켜 두면 같은 일을 두 번 해서 Claude 사용료가 더 나올 수 있어요.
- 새 코드를 받을 때(서버에 접속해서):
  ```bash
  cd ~/youareliar && git pull && bash deploy/setup_server.sh
  ```
- `.env`를 바꿨을 때: 노트북에서 5번으로 다시 복사한 뒤, 서버에서 `sudo systemctl restart lostfound`

### 서버에서 문제가 생겼을 때
- 사이트가 안 열려요 → 서버 상태 `sudo systemctl status lostfound`, 최근 기록 50줄 `sudo journalctl -u lostfound -n 50`, 주소 상태 `tailscale funnel status`
- `[DB 연결 실패]` → 안내대로 노트북의 `.env`를 고친 뒤 위의 '.env를 바꿨을 때'처럼 하세요.
- 오라클에서 'idle(노는) 인스턴스' 메일이 오면 → 회수되기 전에 알려 주세요.

## 새 코드를 받았을 때
```bash
git pull
```
```bash
pip install -r requirements.txt
```
```bash
python -m app.migrate
```
라이브러리와 DB 구조가 바뀌었을 수 있어서 세 줄을 차례로 실행한 뒤 서버를 켭니다. 바뀐 게 없으면 '이미 설치됨', '건너뜀'으로 금방 끝나요.

## 팀원에게 잠깐 보여 주기 (임시 주소)
노트북에서 서버를 켠 채로 Cloudflare의 '임시 터널'을 쓰면, 인터넷 어디서나 들어올 수 있는 임시 주소가 생겨요. 가입은 필요 없어요.
1. 서버를 평소처럼 켭니다.
   ```bash
   uvicorn app.main:app
   ```
2. 처음 한 번만 cloudflared를 설치합니다(다른 PowerShell 창에서). 설치가 끝나면 그 창을 닫고 새로 엽니다.
   ```bash
   winget install --id Cloudflare.cloudflared
   ```
3. 새 PowerShell 창에서 임시 주소를 만듭니다.
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
4. 화면에 나오는 `https://….trycloudflare.com` 주소를 팀원에게 보냅니다.
- 서버 창과 cloudflared 창을 둘 다 켜 두고, 노트북이 잠들지 않게 하세요. 끝낼 때는 두 창에서 Ctrl+C.
- 주소는 켤 때마다 바뀌어요. 주소를 아는 사람은 누구나 들어올 수 있으니 팀원에게만 보내세요.
- 연결이 안 되면 `cloudflared tunnel --protocol http2 --url http://localhost:8000`으로 해 보세요.

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
- 서버 창에 `[DB 연결 실패]` → 서버가 켜질 때 DB에 연결해 보고, 안 되면 이유와 고치는 방법을 바로 아래에 적어 줘요. 안내대로 `DATABASE_URL`을 고치세요.
- `[설정 오류]`로 시작하는 안내 → 안내에 나온 대로 `.env`를 고치면 됩니다.
- `[사진 저장소 오류]` → `SUPABASE_SECRET_KEY`를 Supabase의 **Project Settings → API Keys**에서 다시 복사해 넣어 보세요. `sb_secret_`로 시작하는 키여야 합니다.
- `import torch`에서 `DLL load failed` 오류(윈도우) → 마이크로소프트의 **Visual C++ 재배포 가능 패키지(x64)** 를 설치한 뒤 다시 해 보세요.
- `symlinks` 관련 경고(윈도우) → 모델을 내려받을 때 나오는 안내라서 무시해도 됩니다.
- 서버 창에 `Claude 설명을 받지 못했어요` → 바로 아래 오류 이름을 보세요.
  - `AuthenticationError`: API 키가 틀렸어요. 다시 복사해 넣으세요.
  - `NotFoundError`: `CLAUDE_MODEL`의 모델 이름이 틀렸어요.
  - `credit balance is too low`: 충전한 금액을 다 썼어요. 콘솔에서 충전하세요.
- `No module named ...` → 줄 맨 앞에 `(.venv)`가 있는지 확인하세요. 없으면 `.venv\Scripts\Activate.ps1`(맥은 `source .venv/bin/activate`)을 먼저 실행합니다.

## 알아 둘 점
- **비밀값은 `.env`에만** 넣습니다. `.env`는 `.gitignore`에 등록돼 있어 깃에 올라가지 않습니다.
- Supabase 무료 요금제는 **7일 동안 아무도 쓰지 않으면 프로젝트가 일시정지**됩니다. 대시보드에서 다시 켜면 데이터는 그대로 있습니다.
- **연습 모드**: `.env`에서 `SUPABASE_URL`을 비워 두면 사진을 이 컴퓨터의 `uploads` 폴더에 저장합니다. 이때도 Postgres DB는 필요합니다.
