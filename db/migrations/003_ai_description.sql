-- 003: B 단계 — Claude가 사진을 보고 정리한 내용을 저장할 칸

alter table items add column if not exists ai_description  text;         -- 검색용 설명 (한국어 2~3문장)
alter table items add column if not exists ai_info         jsonb;        -- 종류·색·특징·검색어·개인정보 표시 등 전체 결과
alter table items add column if not exists ai_model        text;         -- 설명을 쓴 Claude 모델 이름
alter table items add column if not exists ai_described_at timestamptz;  -- 설명을 쓴 시각
