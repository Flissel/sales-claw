-- Einen Laden anlegen: Schema, Tabellen, Benutzer, Rechte.
--
-- Aufruf (als supabase_admin, NICHT mit der Laufzeit-Kennung — die hat
-- bewusst kein DDL; gemessen 15.09.2026: "permission denied for schema
-- sales"):
--
--   LADEN_PASSWORT=... psql -v laden=ivan -f db/laden-anlegen.sql
--
-- Das Passwort kommt ueber die Umgebung, nicht ueber argv — es stuende
-- sonst in der Prozessliste. Braucht psql 14+ (`\getenv`).
--
-- Idempotent: ein zweiter Lauf aendert nichts.
\set ON_ERROR_STOP on

\set schema 'sales_':laden
\set rolle 'sales_app_':laden

-- Die Tabellen entstehen als Abzug des bestehenden Schemas. Eine zweite
-- Fassung der Definitionen wuerde beim naechsten Schemawechsel auseinander-
-- laufen; `including all` uebernimmt Spalten, Vorgaben, CHECKs und Indizes.
-- Fremdschluessel deckt `including all` NICHT ab — sie stehen unten.
create schema if not exists :"schema";

create table if not exists :"schema".leads            (like sales.leads            including all);
create table if not exists :"schema".activities       (like sales.activities       including all);
create table if not exists :"schema".drafts           (like sales.drafts           including all);
create table if not exists :"schema".personas         (like sales.personas         including all);
create table if not exists :"schema".benutzer         (like sales.benutzer         including all);
create table if not exists :"schema".medien_meta      (like sales.medien_meta      including all);
create table if not exists :"schema".kalender_quellen (like sales.kalender_quellen including all);

-- Die zwei Fremdschluessel, INNERHALB des neuen Schemas. Zeigten sie auf
-- sales.leads, waere die Trennung schon hier gebrochen.
--
-- WARUM KEIN `do $$ ... $$`-BLOCK: psql ersetzt :'schema' NICHT innerhalb
-- dollar-gequoteter Zeichenketten — der Block bekaeme den Doppelpunkt
-- woertlich und schluege fehl. Drop-dann-Add ist ebenso idempotent und
-- benutzt nur Bezeichner, die psql wirklich einsetzt.
alter table :"schema".activities drop constraint if exists activities_lead_id_fkey;
alter table :"schema".activities add constraint activities_lead_id_fkey
  foreign key (lead_id) references :"schema".leads(id) on delete cascade;

alter table :"schema".drafts drop constraint if exists drafts_lead_id_fkey;
alter table :"schema".drafts add constraint drafts_lead_id_fkey
  foreign key (lead_id) references :"schema".leads(id) on delete set null;

-- Der Benutzer dieses Ladens. Kein DDL, kein DELETE — wie sales_app
-- (db/provision.sql:198-204).
--
-- Das Passwort kommt aus der UMGEBUNG, nicht aus argv: ein `-v passwort=...`
-- stuende in der Prozessliste, und am 12.09.2026 hat genau diese Art von
-- Uebergabe schon einmal einen Token beschaedigt. `\getenv` braucht psql 14
-- oder neuer — pruefen mit `psql --version`, bevor dieses Skript laeuft.
\getenv passwort LADEN_PASSWORT
\if :{?passwort}
\else
\echo 'FEHLER: Umgebungsvariable LADEN_PASSWORT ist nicht gesetzt.'
\quit 1
\endif

select not exists (select 1 from pg_roles where rolname = :'rolle') as fehlt \gset
\if :fehlt
create role :"rolle" login nosuperuser nocreatedb nocreaterole noinherit
  password :'passwort';
\else
alter role :"rolle" password :'passwort';
\endif

grant usage on schema :"schema" to :"rolle";
grant select, insert, update on :"schema".leads            to :"rolle";
grant select, insert         on :"schema".activities       to :"rolle";
grant select, insert, update on :"schema".drafts           to :"rolle";
grant select, insert, update on :"schema".personas         to :"rolle";
grant select, insert, update on :"schema".benutzer         to :"rolle";
grant select, insert, update on :"schema".medien_meta      to :"rolle";
grant select, insert, update on :"schema".kalender_quellen to :"rolle";

-- Die Sperrliste ist GEMEINSAM (Spec §2.1): wer Werbung widerspricht, hat
-- allen widersprochen.
grant usage on schema compliance to :"rolle";
grant select, insert, update on all tables in schema compliance to :"rolle";

-- Und ausdruecklich NICHTS auf dem fremden Schema. Das ist der Kern der
-- Trennung: sie liegt in der Datenbank, nicht im Code.
revoke all on schema sales from :"rolle";
revoke all on all tables in schema sales from :"rolle";
