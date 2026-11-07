-- 005: 회원가입·로그인

-- 회원
create table if not exists users (
    id            bigint generated always as identity primary key,
    username      text not null unique,   -- 아이디 (영어 소문자·숫자·밑줄, 4~20자)
    password_hash text not null,          -- 비밀번호 원래 글자가 아니라, 되돌릴 수 없게 바꾼 값(해시)
    nickname      text not null,          -- 화면에 보일 이름
    created_at    timestamptz not null default now()
);

-- 로그인 상태(세션): 로그인하면 브라우저에 무작위 표시(쿠키)를 주고, 그 표시의 해시를 여기에 적어 둔다.
-- 로그아웃하면 이 줄을 지워서, 같은 표시를 다시 써도 로그인되지 않게 한다.
create table if not exists sessions (
    token_hash text primary key,
    user_id    bigint not null references users (id) on delete cascade,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null
);
create index if not exists sessions_user_id_idx on sessions (user_id);

-- 로그인한 사람이 등록한 물건이면 누가 등록했는지 적어 둔다(로그인 안 했으면 비어 있음).
alter table items add column if not exists user_id bigint references users (id) on delete set null;

alter table users enable row level security;
alter table sessions enable row level security;
