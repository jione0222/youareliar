-- 004: 관리자 기능 — 개인정보 때문에 가린 사진을 관리자가 확인했는지

-- false: Claude가 얼굴이나 개인정보를 봤다면 공개 화면에서 사진을 가린다.
-- true : 관리자가 사진을 직접 보고 "공개해도 된다"고 확인했다.
alter table items add column if not exists privacy_reviewed boolean not null default false;
