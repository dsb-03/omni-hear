-- Omnihear beta backend schema. Run in the Supabase SQL editor.
-- Client uses only the anon key; RLS below is the security boundary.

create table profiles (
  user_id uuid primary key references auth.users on delete cascade,
  beta_access boolean not null default true,
  plan text not null default 'beta',  -- future paid-plan hook
  created_at timestamptz default now()
);

create table feedback (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users,
  kind text not null check (kind in ('bug', 'feature')),
  title text not null,
  body text not null,
  diagnostics text,  -- opt-in metrics excerpt, never transcript content
  created_at timestamptz default now()
);

create table feedback_votes (
  feedback_id bigint references feedback on delete cascade,
  user_id uuid not null default auth.uid(),
  primary key (feedback_id, user_id)
);

create table events (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users,
  event text not null,           -- 'ping', 'activated', ...
  props jsonb not null default '{}',
  created_at timestamptz default now()
);

-- auto-create a profile on signup
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (user_id) values (new.id);
  return new;
end;
$$;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- RLS
alter table profiles enable row level security;
alter table feedback enable row level security;
alter table feedback_votes enable row level security;
alter table events enable row level security;

create policy "own profile read" on profiles
  for select using (user_id = auth.uid());
-- no client insert/update on profiles: trigger + service role only

create policy "own feedback insert" on feedback
  for insert with check (user_id = auth.uid());
create policy "own feedback read" on feedback
  for select using (user_id = auth.uid());

create policy "own vote insert" on feedback_votes
  for insert with check (user_id = auth.uid());
create policy "own vote delete" on feedback_votes
  for delete using (user_id = auth.uid());

-- write-only telemetry: insert allowed, no select policy
create policy "own event insert" on events
  for insert with check (user_id = auth.uid());

-- Metrics (run ad hoc / in a dashboard):
-- DAU:  select count(distinct user_id) from events where event='ping' and created_at::date = current_date;
-- WAU/MAU: same with created_at > now() - interval '7 days' / '30 days';
-- signups: select count(*) from auth.users;
-- activation rate: select count(*) filter (where event='activated') * 1.0 / greatest(count(distinct user_id),1) from events;
