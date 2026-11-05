-- 002: A 검색용 벡터(숫자 목록)를 저장하는 표

-- pgvector: Postgres에서 벡터를 저장하고 '얼마나 가까운지' 계산하게 해 주는 확장 기능.
-- Supabase는 확장 기능을 extensions 스키마에 두기를 권장해서, 그 스키마가 있으면 거기에 설치한다.
do $$
begin
    if exists (select 1 from pg_namespace where nspname = 'extensions') then
        create extension if not exists vector with schema extensions;
    else
        create extension if not exists vector;
    end if;
end
$$;

-- 물건 하나에 벡터가 여러 개 생길 수 있다.
--   model: 어떤 AI 모델로 만든 벡터인지 (모델을 바꿔도 예전 벡터와 섞이지 않게)
--   kind : image = 사진 벡터(A 단계), description = Claude가 쓴 설명의 벡터(B 단계에서 사용)
create table if not exists item_vectors (
    item_id    bigint not null references items (id) on delete cascade,  -- 물건이 지워지면 벡터도 같이 지운다
    model      text   not null,
    kind       text   not null check (kind in ('image', 'description')),
    embedding  vector not null,
    created_at timestamptz not null default now(),
    primary key (item_id, model, kind)
);

alter table item_vectors enable row level security;
