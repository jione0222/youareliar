-- 008: 쪽지함 — 회원이 관리자(선생님)에게 쪽지로 문의하고 답장을 받는다.
-- 대화는 회원마다 하나다. 그 회원이 보낸 쪽지와 관리자가 그 회원에게 보낸 쪽지가 한 줄로 이어진다.
create table if not exists messages (
    id         bigint generated always as identity primary key,
    user_id    bigint not null references users (id) on delete cascade,  -- 어느 회원과 주고받은 쪽지인지
    from_admin boolean not null default false,                           -- true: 관리자가 보냄, false: 회원이 보냄
    item_id    bigint references items (id) on delete set null,          -- 어떤 물건에 대한 쪽지인지(없어도 됨)
    body       text not null check (char_length(body) between 1 and 1000),
    created_at timestamptz not null default now(),
    read_at    timestamptz                                               -- 받는 쪽이 읽은 때(안 읽었으면 비어 있음)
);
create index if not exists messages_user_id_idx on messages (user_id, id);

alter table messages enable row level security;
