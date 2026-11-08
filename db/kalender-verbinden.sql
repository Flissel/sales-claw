-- Kalender verbinden (Spec 2026-11-08): jede Kalenderquelle hat einen Besitzer
-- und einen Bereich (business/privat), dazu Konten (Google) und die
-- Abgleich-Tabelle kalender_termine. Aufruf je Schema (als supabase_admin):
--
--   psql -v ON_ERROR_STOP=1 -v schema=sales_test -v besitzer=felix \
--        -f db/kalender-verbinden.sql
--
-- :besitzer = Laden-Besitzer. Bestehende Quellen ohne Besitzer gehoeren ihm und
-- werden 'privat' (Spec §2.9). Die Variable ist nur noetig, solange es Zeilen
-- mit `besitzer is null` gibt: fehlt sie dann, bricht das Skript ab, bevor
-- Altzeilen gefuellt oder Pflicht-/Check-Regeln gesetzt werden (die rein
-- additiven Schritte davor - Tabelle kalender_konten, nullbare Spalten - sind
-- schon gelaufen und harmlos). Technik: `\if :{?besitzer}` prueft, ob psql die
-- Variable kennt; sonst wird sie auf '' gesetzt, und der Pruefblock unten
-- wirft eine Ausnahme, falls Altzeilen existieren.
--
-- Bewusst NICHT im Schema-Loop von db/provision.sql (wie post-sammelstelle.sql):
-- so laesst sich der Block auf sales_test einspielen, ohne `sales` anzufassen.
-- Neue Laeden muessen es zusaetzlich einspielen (siehe db/laden-anlegen.sql).
-- Idempotent: ein zweiter Lauf aendert nichts.
--
-- psql ersetzt :"schema" nicht innerhalb von $$-Bloecken. Darum stehen
-- Schemaname und Besitzer in Sitzungsvariablen (set_config).
\set ON_ERROR_STOP on

\if :{?besitzer}
\else
  \set besitzer ''
\endif

select set_config('kv.schema', :'schema', false);
select set_config('kv.besitzer', :'besitzer', false);

-- Konten (Google). Das Zugangsgeheimnis liegt nur versiegelt in der Tabelle.
create table if not exists :"schema".kalender_konten (
  id uuid primary key default gen_random_uuid(),
  besitzer text not null,
  anbieter text not null check (anbieter in ('google')),
  adresse text not null,
  zugang_versiegelt text,
  kalender_liste jsonb not null default '[]',
  aktiv boolean not null default true,
  created_at timestamptz default now(),
  unique (besitzer, anbieter, adresse)
);

-- Neue Spalten der Quellen. besitzer zunaechst nullbar (Rueckfuellung folgt).
alter table :"schema".kalender_quellen add column if not exists besitzer text;
alter table :"schema".kalender_quellen add column if not exists bereich text default 'privat';
alter table :"schema".kalender_quellen add column if not exists konto_id uuid
  references :"schema".kalender_konten(id);
alter table :"schema".kalender_quellen add column if not exists google_id text;

-- Abbruch, wenn Altzeilen einen Besitzer brauchen, aber keiner uebergeben wurde.
do $$
declare
  n int;
begin
  -- besitzer wurde oben angelegt, die Spalte existiert hier in jedem Fall.
  execute format('select count(*) from %I.kalender_quellen where besitzer is null',
                 current_setting('kv.schema')) into n;
  if n > 0 and current_setting('kv.besitzer') = '' then
    raise exception 'besitzer fehlt: % Quelle(n) ohne Besitzer - mit -v besitzer=<name> aufrufen', n;
  end if;
end $$;

-- Rueckfuellung: Altzeilen gehoeren dem Laden-Besitzer und sind privat.
update :"schema".kalender_quellen set besitzer = :'besitzer' where besitzer is null;
update :"schema".kalender_quellen set bereich = 'privat' where bereich is null;

-- Der Default war nur fuers Rueckfuellen da: neu verbundene Quellen haben
-- keinen Standard, der Bereich ist Pflicht.
alter table :"schema".kalender_quellen alter column bereich drop default;
alter table :"schema".kalender_quellen alter column bereich set not null;
alter table :"schema".kalender_quellen alter column besitzer set not null;

alter table :"schema".kalender_quellen drop constraint if exists kalender_quellen_bereich_check;
alter table :"schema".kalender_quellen add constraint kalender_quellen_bereich_check
  check (bereich in ('business','privat'));
alter table :"schema".kalender_quellen drop constraint if exists kalender_quellen_art_check;
alter table :"schema".kalender_quellen add constraint kalender_quellen_art_check
  check (art in ('ics','google'));

-- Der Name ist nur noch je Besitzer eindeutig.
-- Den alten globalen Unique-Index auf (anzeigename) entfernen, gleich unter
-- welchem Namen: Schemata aus db/laden-anlegen.sql (`like ... including all`)
-- tragen einen automatisch vergebenen Namen.
do $$
declare
  i record;
  k record;
begin
  for i in
    select ic.oid, ic.relname
      from pg_index x
      join pg_class ic on ic.oid = x.indexrelid
      join pg_class tc on tc.oid = x.indrelid
      join pg_namespace n on n.oid = tc.relnamespace
     where n.nspname = current_setting('kv.schema')
       and tc.relname = 'kalender_quellen'
       and x.indisunique and not x.indisprimary
       and x.indnkeyatts = 1
       and x.indpred is null
       and (select a.attname from pg_attribute a
             where a.attrelid = tc.oid and a.attnum = x.indkey[0]) = 'anzeigename'
  loop
    -- Haengt der Index an einer Unique-Constraint, faellt er nur mit ihr.
    select c.conname, c.conrelid::regclass::text into k
      from pg_constraint c where c.conindid = i.oid;
    if k.conname is not null then
      execute format('alter table %s drop constraint %I', k.conrelid, k.conname);
    else
      execute format('drop index %I.%I', current_setting('kv.schema'), i.relname);
    end if;
  end loop;
end $$;
create unique index if not exists kalender_quellen_besitzer_name_idx
  on :"schema".kalender_quellen (besitzer, anzeigename);

-- Abgeglichene Termine je Quelle. Fuer fremde Privat-Quellen bleiben titel und
-- ort leer (Spec §6.3); das sorgt der Abgleich, nicht die Tabelle.
create table if not exists :"schema".kalender_termine (
  quelle_id uuid not null references :"schema".kalender_quellen(id),
  uid text not null default '',
  beginn timestamptz not null,
  ende timestamptz not null,
  ganztaegig boolean not null default false,
  frei boolean not null default false,
  titel text,
  ort text,
  abgeglichen_am timestamptz not null default now()
);
create index if not exists kalender_termine_beginn_idx
  on :"schema".kalender_termine (beginn);
create index if not exists kalender_termine_quelle_idx
  on :"schema".kalender_termine (quelle_id);

-- Rechte: sales_app fuer `sales`/`sales_test`, sales_app_<laden> sonst.
-- Konten: lesen, anlegen, aendern. Termine: zusaetzlich Loeschrecht, weil der
-- Abgleich Termine ersetzt (Spec §5).
do $$
declare
  s text := current_setting('kv.schema');
  rolle text;
begin
  if s in ('sales', 'sales_test') then
    rolle := 'sales_app';
  elsif exists (
      select 1 from pg_roles where rolname = 'sales_app_' || substr(s, 7)) then
    rolle := 'sales_app_' || substr(s, 7);
  end if;
  if rolle is null then
    raise notice 'WARNUNG: keine Rechte vergeben fuer Schema %: Rolle % existiert nicht', s, 'sales_app_' || substr(s, 7);
    return;
  end if;
  execute format('grant select, insert, update on %I.kalender_konten to %I', s, rolle);
  execute format('grant select, insert, update, delete on %I.kalender_termine to %I', s, rolle);
end $$;
