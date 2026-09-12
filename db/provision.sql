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
          check (channel in ('email','whatsapp','linkedin','voice','video','meeting_invite','telegram')),
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
    -- E1 (31.08.2026): UI-Anmeldung. Kein DELETE — Offboarding ist
    -- aktiv=false, der Name bleibt fuer approved_by-Nachweise lesbar.
    execute format($ddl$
      create table if not exists %I.benutzer (
        name text primary key check (name !~ '[|:]' and name <> ''),
        rolle text not null check (rolle in ('lesen','freigeben')),
        passwort_hash text not null,
        aktiv boolean not null default true,
        created_at timestamptz not null default now()
      )$ddl$, s);
    -- UI-Plan Schritt 4 (02.09.2026): je Datei im Medienordner der
    -- Schalter "Bot darf senden" und die Herkunft. Ohne Zeile gilt: darf
    -- senden, hochgeladen — der Bestand bleibt unveraendert.
    execute format($ddl$
      create table if not exists %I.medien_meta (
        dateiname text primary key
          check (dateiname <> '' and dateiname !~ '[/\\]'),
        bot_darf_senden boolean not null default true,
        herkunft text not null default 'hochgeladen'
          check (herkunft in ('hochgeladen','chat','system')),
        updated_at timestamptz not null default now()
      )$ddl$, s);
    -- CC fuer E-Mail-Entwuerfe (03.09.2026); add column, weil die Tabelle
    -- auf beiden Schemata laengst existiert.
    execute format('alter table %I.drafts add column if not exists cc text', s);
    -- Telegram als Kanal (12.09.2026): sales-claw ist seit dem
    -- Betreiber-Entscheid der einzige Versandweg des Hauses, und Marketings
    -- eigener Telegram-Versender ist gesperrt. Ohne diese Zeilen scheiterte
    -- JEDER Telegram-Entwurf am CHECK — und zwar erst beim Insert, also
    -- lange nachdem der Agent den Text geschrieben hat. Drop+Add statt
    -- „add column if not exists", weil man einen CHECK nicht nachruesten
    -- kann; idempotent ueber `drop constraint if exists`.
    execute format('alter table %I.drafts drop constraint if exists drafts_channel_check', s);
    execute format($chk$alter table %I.drafts add constraint drafts_channel_check
      check (channel in ('email','whatsapp','linkedin','voice','video','meeting_invite','telegram'))$chk$, s);
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
grant select, insert, update on sales.benutzer to sales_app;
grant select, insert, update on sales.medien_meta to sales_app;
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

-- ---------------------------------------------------------------------------
-- Betreiber-Wünsche 22.08.2026 (Entwürfe verwerfen, Chat-Reports): ebenfalls
-- KEIN DDL. Aus denselben drei Gründen wie oben — und mit denselben Folgen für
-- den, der es später anders machen will.
--
-- * **Entwurf verwerfen** braucht keinen Status „verworfen": der CHECK auf
--   `drafts.status` kennt `rejected` seit Stufe 2, und das ist der Zielwert.
--   Unterschieden wird im Protokoll, nicht im Status — `ablehnung` (aus
--   `pending`) gegen `verwerfung` (aus `failed`/`approved`, mit `aus_status`
--   im Payload). Nach dem Übergang sagt die drafts-Zeile selbst nicht mehr,
--   woher sie kam; nachtragen ginge nie, weil es auf `activities` kein UPDATE
--   gibt.
-- * **Chat-Report** braucht keine Tabelle und keine Spalte: er IST eine Zeile
--   in `activities` (`type='chat_report'`), und die Zusammenfassungsgrenze
--   steht in seinem Payload als Paar (`bis_zeitpunkt`, `bis_aktivitaet_id`).
--   Das Paar und nicht der Zeitstempel allein, weil `created_at` die
--   TRANSAKTIONSZEIT ist: zwei Zeilen derselben Transaktion tragen denselben
--   Wert (Befund M10), und „alles bis <Zeit>" wäre dort ein Münzwurf.
--   Gelesen wird wieder „jüngste Zeile gewinnt".
--
-- Append-only bleibt damit unangetastet: ein Report LÖSCHT nichts, er kommt
-- dazu. Die zusammengefassten Einzelnachrichten bleiben vollzählig in
-- `activities` und verschwinden ausschließlich aus der ANZEIGE
-- (`profil_lesen`, Kontaktseite) — im Wortlaut stehen sie über
-- `chat_verlauf(lead_id)`. Auch an diesem Skript ist nichts zu tun.
-- ---------------------------------------------------------------------------
