-- 007: 물건을 찾아간 사람 기록 (관리자와 그 물건을 등록한 사람만 본다)
alter table items add column if not exists claimant_name text;        -- 찾아간 사람 이름
alter table items add column if not exists claimant_student_id text;  -- 찾아간 사람 학번
alter table items add column if not exists returned_at timestamptz;   -- '주인 찾음'으로 바꾼 때
