-- sales-claw Stufe 2 — Schema-Provisionierung.
-- Anwenden als supabase_admin auf debian-supabase-db-1 (VM .65).
-- Muster: secondbrain-mcp/docs/bizplan-provision.sql — additiv, kein
-- Eingriff in bestehende Schemata, keine pg_hba-Änderung.
\set ON_ERROR_STOP on

-- Extensions werden auf einer geteilten Instanz NICHT automatisch
-- installiert — das Skript prueft nur, dass sie vorliegen. Fehlen sie,
-- ist das eine bewusste Admin-Entscheidung ausserhalb dieses Skripts.
do $$
begin
  if not exists (select 1 from pg_extension where extname = 'vector') then
    raise exception 'Extension "vector" fehlt. Als Admin installieren: create extension vector with schema public;';
  end if;
  if not exists (select 1 from pg_extension where extname = 'pgcrypto') then
    raise exception 'Extension "pgcrypto" fehlt. Als Admin installieren: create extension pgcrypto with schema extensions;';
  end if;
end $$;

-- Rolle ohne DDL. Das Passwort setzt der Anwender NACH dem Einspielen per
-- gesondertem ALTER ROLE über stdin — nie in diesem Skript, nie im Repo.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'sales_app') then
    create role sales_app login nosuperuser nocreatedb nocreaterole noinherit;
  end if;
end $$;

create schema if not exists sales;
create schema if not exists sales_test;
grant usage on schema sales to sales_app;
grant usage on schema sales_test to sales_app;

-- Identische Tabellen in beiden Schemata; nur die Rechte unterscheiden sich.
do $$
declare s text;
begin
  foreach s in array array['sales','sales_test'] loop
    execute format($ddl$
      create table if not exists %I.leads (
        id uuid primary key default gen_random_uuid(),
        name text not null,
        email text,
        phone text,
        company text,
        title text,
        source text,
        consent_status text not null default 'unknown'
          check (consent_status in ('opt_in','existing_customer','inbound','unknown')),
        status text not null default 'new'
          check (status in ('new','researched','qualified','contacted','replied','meeting','won','lost')),
        score int,
        score_breakdown jsonb,
        enrichment jsonb not null default '{}'::jsonb,
        notes text,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now()
      )$ddl$, s);
    execute format($ddl$
      create table if not exists %I.activities (
        id uuid primary key default gen_random_uuid(),
        lead_id uuid references %I.leads(id) on delete cascade,
        type text not null,
        payload jsonb,
        actor text not null default 'agent' check (actor in ('agent','human','cron')),
        created_at timestamptz not null default now()
      )$ddl$, s, s);
    execute format($ddl$
      create table if not exists %I.drafts (
        id uuid primary key default gen_random_uuid(),
        lead_id uuid references %I.leads(id) on delete set null,
        channel text not null
          check (channel in ('email','whatsapp','linkedin','voice','video','meeting_invite')),
        recipient text not null,
        subject text,
        body text not null,
        media_ref text,
        status text not null default 'pending'
          check (status in ('pending','approved','rejected','sent','failed')),
        approved_by text,
        approved_at timestamptz,
        sent_at timestamptz,
        error text,
        created_at timestamptz not null default now()
      )$ddl$, s, s);
    execute format($ddl$
      create table if not exists %I.personas (
        id uuid primary key default gen_random_uuid(),
        name text not null,
        titles text[] not null default '{}',
        pains text[] not null default '{}',
        industries text[] not null default '{}',
        notes text,
        embedding vector(1536),
        created_at timestamptz not null default now()
      )$ddl$, s);
    execute format('create index if not exists leads_status_idx on %I.leads (status)', s);
    execute format('create index if not exists activities_lead_idx on %I.activities (lead_id, created_at desc)', s);
    execute format('create index if not exists drafts_status_idx on %I.drafts (status, created_at desc)', s);
  end loop;
end $$;

-- updated_at-Pflege, Eigentümer supabase_admin.
create or replace function sales.set_updated_at() returns trigger language plpgsql as
$fn$ begin new.updated_at = now(); return new; end; $fn$;
create or replace function sales_test.set_updated_at() returns trigger language plpgsql as
$fn$ begin new.updated_at = now(); return new; end; $fn$;
drop trigger if exists leads_updated_at on sales.leads;
create trigger leads_updated_at before update on sales.leads
  for each row execute function sales.set_updated_at();
drop trigger if exists leads_updated_at on sales_test.leads;
create trigger leads_updated_at before update on sales_test.leads
  for each row execute function sales_test.set_updated_at();

-- Rechte Demo-Schema: activities append-only als Datenbank-Garantie.
grant select, insert, update on sales.leads    to sales_app;
grant select, insert         on sales.activities to sales_app;
grant select, insert, update on sales.drafts   to sales_app;
grant select, insert, update on sales.personas to sales_app;
-- Bewusst NICHT vergeben: DELETE (nirgends), UPDATE/TRUNCATE auf activities.

-- Testschema: voll berechtigt inkl. TRUNCATE — die Test-Fixture setzt
-- zwischen Tests zurück. Die Testsuite darf NIE gegen `sales` laufen.
grant select, insert, update, delete, truncate
  on all tables in schema sales_test to sales_app;

-- ---------------------------------------------------------------------------
-- Stufe 11 (Einordnung eingehender Absender): KEINE neue Tabelle. Bewusst.
--
-- Der Plan sah `sales.lid_zuordnung` (lid, telefon, quelle, gesehen_am) vor.
-- Umgesetzt wurde sie NICHT — die Zuordnungen liegen als Aktivitätstypen in
-- `activities`: `lid_zuordnung`, `absender_rueckfrage`, `absender_ignoriert`,
-- `absender_beachtet`, `eingang_ignoriert` (siehe sales-mcp/server.py).
-- Drei Gründe, hier notiert, damit niemand die Tabelle später „nachträgt":
--
--   1. `sales_app` hat kein DDL. Eine neue Tabelle wäre Admin-Arbeit in
--      BEIDEN Schemata; bis dahin wäre die ganze Stufe tot.
--   2. Der `grant … on all tables in schema sales_test` oben ist eine
--      MOMENTAUFNAHME. Eine später ergänzte Tabelle trägt ihn nicht, und die
--      Testsuite bräche mit 42501 an einer Stelle, die wie ein Testfehler
--      aussieht und keiner ist.
--   3. `activities` ist append-only — genau das verlangt die Stufe („kein
--      DELETE, ein Gegen-Ereignis"). Eine Zuordnung ist ein Ereignis mit
--      Zeitpunkt und Herkunft, kein Stammdatum: dass eine Kennung heute zu
--      einer Nummer auflöst und morgen zu einer anderen, ist Historie.
--
-- Gelesen wird deshalb überall „jüngste Zeile gewinnt", wie bei
-- wiedervorlage/wiedervorlage_erledigt. Es ist an diesem Skript nichts zu tun.
-- ---------------------------------------------------------------------------
