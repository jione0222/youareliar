-- 001: 습득물(주운 물건) 표 만들기

create table if not exists items (
    id            bigint generated always as identity primary key,  -- 자동으로 붙는 번호
    created_at    timestamptz not null default now(),                -- 등록한 시각
    photo_path    text not null,   -- 저장소 안의 사진 경로 (상세 화면용)
    thumb_path    text not null,   -- 저장소 안의 작은 사진 경로 (목록용)
    storage_place text not null,   -- 보관 장소 (예: 교무실)
    found_place   text,            -- 발견 장소 (예: 3층 복도)
    found_date    date,            -- 발견 날짜
    memo          text,            -- 등록한 사람이 쓴 설명 (선택)
    status        text not null default 'stored'
                  check (status in ('stored', 'returned')),  -- stored = 보관 중, returned = 주인 찾음
    hidden        boolean not null default false              -- 관리자가 숨긴 글이면 true
);

-- 목록을 '최근 등록 순'으로 빨리 꺼내기 위한 색인
create index if not exists items_created_at_idx on items (created_at desc);

-- Supabase는 public 스키마의 표를 인터넷 API로도 열어 둔다.
-- RLS(행 단위 보안)를 켜고 허용 규칙을 하나도 만들지 않으면, 그 API로는 아무도 읽거나 쓸 수 없다.
-- 우리 서버는 표를 만든 계정으로 DB에 직접 연결하므로 영향을 받지 않는다.
alter table items enable row level security;
