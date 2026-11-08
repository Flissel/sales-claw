-- Freigabe-Eingang: eine allgemeine Eingangsbox fuer Dinge, die ein Mensch
-- freigeben soll (Debugger-PRs, Selbstbild-Rueckfragen, Kursfreigaben,
-- Entwuerfe). Aufruf je Schema (als supabase_admin):
--
--   psql -v ON_ERROR_STOP=1 -v schema=sales_test -f db/freigabe-eingang.sql
--
-- Bewusst NICHT im Schema-Loop von db/provision.sql (wie post-sammelstelle.sql):
-- so laesst sich der Block auf sales_test einspielen und pruefen, ohne die
-- Produktion (`sales`) anzufassen. Idempotent: ein zweiter Lauf aendert nichts.
--
-- psql ersetzt :"schema" nicht innerhalb von $$-Bloecken. Darum steht der
-- Schemaname fuer den Rechte-Block in einer Sitzungsvariable (set_config).
\set ON_ERROR_STOP on

select set_config('freigabe.schema', :'schema', false);

-- Ein Eintrag je Sache, die auf eine Entscheidung wartet. Pro (herkunft,
-- quelle_ref) darf nur EIN Eintrag offen sein (partieller Unique-Index).
create table if not exists :"schema".freigabe_eintraege (
  id uuid primary key default gen_random_uuid(),
  kennung text unique not null check (kennung ~ '^fg-[a-z2-7]{10}$'),
  herkunft text not null check (herkunft in
    ('debugger-claw','selbstbild','werkstatt','sales','marketing')),
  art text not null check (art in
    ('debugger_pr','selbstbild_rueckfrage','kursfreigabe','entwurf')),
  quelle_ref text not null,
  titel text not null check (length(titel) <= 200),
  link text,
  details jsonb not null default '{}',
  draft_id uuid references :"schema".drafts(id),
  status text not null default 'offen' check (status in
    ('offen','ausgefuehrt','verworfen','erledigt')),
  rowboat_stand text not null default 'ungesichtet' check (rowboat_stand in
    ('ungesichtet','vorgeschlagen','angenommen','abgelehnt','abgehakt')),
  rowboat_seit timestamptz,
  rowboat_aufgeraeumt boolean not null default false,
  vermerk text,
  erstellt_am timestamptz default now(),
  geschlossen_am timestamptz,
  geschlossen_von text
);

create unique index if not exists freigabe_eintraege_offen_je_quelle
  on :"schema".freigabe_eintraege (herkunft, quelle_ref) where status = 'offen';
create index if not exists freigabe_eintraege_status_erstellt
  on :"schema".freigabe_eintraege (status, erstellt_am);

-- Auftraege an die Abholer (selbstbild / werkstatt), die eine Entscheidung
-- in ihrem eigenen System nachziehen.
create table if not exists :"schema".freigabe_auftraege (
  id uuid primary key default gen_random_uuid(),
  eintrag_id uuid not null references :"schema".freigabe_eintraege(id),
  art text not null check (art in ('selbstbild_label','kurs_freigabe_zeigen')),
  abholer text not null check (abholer in ('selbstbild','werkstatt')),
  nutzlast jsonb not null,
  status text not null default 'offen' check (status in
    ('offen','laeuft','erfolg','fehler')),
  angefordert_von text not null,
  fehler text,
  erstellt_am timestamptz default now(),
  abgeholt_am timestamptz,
  erledigt_am timestamptz
);

create index if not exists freigabe_auftraege_abholer_status
  on :"schema".freigabe_auftraege (abholer, status, erstellt_am);

-- Zugangsschluessel der einliefernden Systeme (nur der Hash liegt hier).
create table if not exists :"schema".freigabe_schluessel (
  herkunft text primary key check (herkunft in
    ('debugger-claw','selbstbild','werkstatt')),
  hash text not null,
  aktiv boolean default true,
  angelegt_am timestamptz default now()
);

-- Rechte: sales_app liest, legt an und aendert, loescht nie. In sales_test
-- zusaetzlich truncate (die Fixtures raeumen auf). Der Blankett-Grant im
-- Testschema-Block von provision.sql erfasst neue Tabellen nicht.
do $$
declare
  s text := current_setting('freigabe.schema');
  rechte text := 'select, insert, update';
  t text;
begin
  if s = 'sales_test' then
    rechte := 'select, insert, update, truncate';
  end if;
  foreach t in array array['freigabe_eintraege','freigabe_auftraege','freigabe_schluessel'] loop
    execute format('grant %s on %I.%I to sales_app', rechte, s, t);
  end loop;
end $$;
