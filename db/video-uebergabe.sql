-- Vorbereitete Video-Uebergaben aus Rowboat (Konzept-Flaeche, Spec 14, 14.11.2026).
-- Rowboat legt nur eine Uebergabe an; der Auftrag entsteht erst, wenn der Betreiber auf der
-- Werkbank-Seite "Ja, uebergeben" drueckt. Aufruf je Schema (als supabase_admin):
--
--   psql -v ON_ERROR_STOP=1 -v schema=sales_test -f db/video-uebergabe.sql
--
-- Bewusst NICHT im Schema-Loop von db/provision.sql (wie freigabe-eingang.sql). Idempotent:
-- `create table if not exists`, `create index if not exists`, Rechte sind wiederholbar; ein zweiter
-- Lauf aendert nichts. psql ersetzt :"schema" nicht in $$-Bloecken, darum steht der Schemaname fuer
-- den Rechte-Block in einer Sitzungsvariable.
\set ON_ERROR_STOP on

select set_config('uebergabe.schema', :'schema', false);

create table if not exists :"schema".video_uebergabe (
  id uuid primary key default gen_random_uuid(),
  konzept jsonb not null,
  konzept_sha text not null,
  status text not null default 'offen' check (status in
    ('offen','wird_uebergeben','bestaetigt','verworfen','abgelaufen')),
  fehler text,
  auftrag_id uuid,
  erstellt_am timestamptz not null default now(),
  entschieden_am timestamptz,
  entschieden_von text
);

-- Dasselbe Konzept (gleicher Hash) nie zweimal gleichzeitig offen.
create unique index if not exists video_uebergabe_offen_je_hash
  on :"schema".video_uebergabe (konzept_sha) where status in ('offen','wird_uebergeben');
create index if not exists video_uebergabe_status_erstellt
  on :"schema".video_uebergabe (status, erstellt_am);

-- Rechte: sales_app liest, legt an und aendert, loescht nie. In sales_test zusaetzlich truncate.
do $$
declare
  s text := current_setting('uebergabe.schema');
  rechte text := 'select, insert, update';
begin
  if s = 'sales_test' then
    rechte := 'select, insert, update, truncate';
  end if;
  execute format('grant %s on %I.video_uebergabe to sales_app', rechte, s);
end $$;
