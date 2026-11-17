-- 006: 정렬(조회순), 종류 필터, 습득자 연락처

-- 상세 화면을 연 횟수 (조회순 정렬에 쓴다)
alter table items add column if not exists view_count integer not null default 0;

-- 물건 종류: 의류 / 전자기기 / 학용품 / 물병·텀블러 / 가방·지갑 / 액세서리 / 운동용품 / 기타
-- 등록한 사람이 고르거나, Claude가 사진을 보고 고른다. 모르면 비어 있다.
alter table items add column if not exists category text;
create index if not exists items_category_idx on items (category);

-- 습득자 연락처 (선택). 로그인한 사람에게만 보여 준다.
alter table items add column if not exists finder_name text;
alter table items add column if not exists finder_phone text;
