-- 009: 등록할 때 주운 사람이 직접 다는 제목(선택). 예: '파란 텀블러'
alter table items add column if not exists title text;
