-- Post-Sammelstelle, Stufe 1 (Spec 2026-10-30-post-sammelstelle-design.md):
-- Tabellen, Rechte und Startabteilungen. Aufruf je Schema (als supabase_admin):
--
--   psql -v ON_ERROR_STOP=1 -v schema=sales_test -f db/post-sammelstelle.sql
--
-- Bewusst NICHT im Schema-Loop von db/provision.sql (Ruling R1): so laesst sich
-- der Block auf sales_test einspielen und pruefen, ohne die Produktion
-- (`sales`) anzufassen. Neue Laeden muessen es zusaetzlich einspielen
-- (siehe db/laden-anlegen.sql). Idempotent: ein zweiter Lauf aendert nichts.
--
-- psql ersetzt :"schema" nicht innerhalb von $$-Bloecken. Darum steht der
-- Schemaname fuer den Rechte-Block in einer Sitzungsvariable (set_config).
\set ON_ERROR_STOP on

select set_config('post.schema', :'schema', false);

-- Konten, aus denen die Sammelstelle liest. Das Zugangsgeheimnis liegt nur
-- versiegelt in der Tabelle (zugang_versiegelt), nie im Klartext.
create table if not exists :"schema".post_konten (
  id uuid primary key default gen_random_uuid(),
  besitzer text not null,
  kennung text unique not null,
  anbieter text not null check (anbieter in ('gmx','gmail','namecheap')),
  adresse text not null,
  zugang_versiegelt text,
  quelle text not null check (quelle in ('env','ui')),
  uidvalidity bigint,
  letzte_uid bigint,
  altbestand_fertig boolean default false,
  aktiv boolean default true,
  angelegt_am timestamptz default now()
);

-- Je gesehene Mail eine Zeile. suchtext nimmt den Text sensibler Mails NICHT
-- auf: was als sensibel gilt, soll sich ueber die Suche nicht herausziehen
-- lassen (Spec §5). Generated column, damit das auch bei spaeterer
-- Aenderung von `sensibel` automatisch stimmt.
create table if not exists :"schema".post_mails (
  id uuid primary key default gen_random_uuid(),
  konto_id uuid references :"schema".post_konten(id),
  imap_uid bigint not null,
  message_id text not null,
  besitzer text not null,
  von text,
  an text,
  betreff text,
  datum timestamptz,
  text text,
  auszug text,
  anhaenge text[] default '{}',
  bereich text check (bereich in ('privat','business')),
  fach text,
  sensibel boolean not null default false,
  einordnung_quelle text check (einordnung_quelle in ('regel','modell','mensch')),
  begruendung text,
  eingeordnet_am timestamptz,
  status text not null default 'neu' check (status in ('neu','eingeordnet','fehler')),
  fehler text,
  gesehen_am timestamptz default now(),
  suchtext tsvector generated always as (to_tsvector('german'::regconfig,
    coalesce(betreff,'') || ' ' || coalesce(von,'') || ' ' ||
    case when sensibel then '' else coalesce(text,'') end)) stored,
  unique (konto_id, imap_uid)
);
-- Ruling R8: Fehlversuche ausserhalb des Gateways je Mail; ab 3 wird die Mail
-- `fehler`, damit eine einzelne kaputte Mail die Einordnung nicht blockiert.
alter table :"schema".post_mails
  add column if not exists versuche int not null default 0;
-- I1: traegt die Mail einen text/calendar-Teil? Beim Abholen gesetzt; nur dann
-- liest postfach_mail_lesen die Mail einmal live, um eine Kalenderantwort
-- (REPLY/COUNTER) am Kontakt festzuhalten (wie frueher postfach.lesen).
alter table :"schema".post_mails
  add column if not exists kalenderteil boolean not null default false;
-- M3: die Mail hatte keine Message-ID; message_id ist dann ein Platzhalter
-- "<kennung>:<uid>@sales-post". Solche Mails taugen nicht fuer die
-- Identitaetspruefung vor Antworten/Aufraeumen (post:-uid wird abgelehnt).
alter table :"schema".post_mails
  add column if not exists message_id_ersatz boolean not null default false;
update :"schema".post_mails set message_id_ersatz = true
  where not message_id_ersatz and message_id like '%:%@sales-post';
-- Fail closed (R9): NULL bei `sensibel` darf es nicht geben. Bestehende
-- Installationen werden nachgezogen; beides ist beliebig oft wiederholbar.
update :"schema".post_mails set sensibel = false where sensibel is null;
alter table :"schema".post_mails alter column sensibel set not null;
create index if not exists post_mails_such_idx
  on :"schema".post_mails using gin (suchtext);
create index if not exists post_mails_besitzer_msg_idx
  on :"schema".post_mails (besitzer, message_id);

create table if not exists :"schema".post_regeln (
  id uuid primary key default gen_random_uuid(),
  muster text not null,
  feld text not null check (feld in ('von','betreff')),
  bereich text,
  fach text,
  sensibel boolean default false,
  angelegt_von text,
  angelegt_am timestamptz default now()
);
-- Ruling R13: eine Regel aus „für diesen Absender immer so“ gilt nur fuer die
-- Post ihres Besitzers - sonst ordnete Annas Entscheidung auch Bens Mails ein
-- (und machte sie z. B. privat oder business). NULL = globale Regel, nur fuer
-- spaetere Betreiber-Pflege; die Oberflaeche legt keine an.
alter table :"schema".post_regeln
  add column if not exists besitzer text;

create table if not exists :"schema".post_abteilungen (
  name text primary key
);
-- `fach` ist der Primary Key (ein Fach gehoert hoechstens einer Abteilung,
-- Spec §7). Die Tabelle bezieht sich NUR auf Business-Faecher; „Rechnungen“
-- und „Werbung“ gibt es in beiden Bereichen, gemeint ist hier jeweils das
-- Business-Fach.
create table if not exists :"schema".post_abteilung_faecher (
  abteilung text references :"schema".post_abteilungen(name),
  fach text not null,
  primary key (fach)
);
create table if not exists :"schema".benutzer_abteilungen (
  benutzer text,
  abteilung text references :"schema".post_abteilungen(name),
  primary key (benutzer, abteilung)
);

-- Leitung ist eine Eigenschaft der Person, nicht der Abteilung (Spec §7).
alter table :"schema".benutzer
  add column if not exists leitung boolean not null default false;

-- Startabteilungen (Spec §7), anpassbar in der Oberflaeche.
insert into :"schema".post_abteilungen (name) values
  ('Vertrieb'), ('Buchhaltung'), ('Marketing'), ('Recruiting'), ('Technik')
  on conflict do nothing;
insert into :"schema".post_abteilung_faecher (abteilung, fach) values
  ('Vertrieb', 'Kunden & Anfragen'),
  ('Vertrieb', 'Partner & Netzwerk'),
  ('Buchhaltung', 'Rechnungen'),
  ('Marketing', 'Newsletter & Branche'),
  ('Marketing', 'Werbung'),
  ('Recruiting', 'Bewerbungen & Jobs'),
  ('Technik', 'Tools & Dienste')
  on conflict do nothing;

-- Rechte wie bei postfach_mails (provision.sql): sales_app fuer `sales`,
-- sales_app_<laden> fuer sales_<laden> falls die Rolle existiert. Kein delete.
-- Ausnahme sales_test: die Tests laufen als sales_app (ohne Rechte sieht sie
-- die Tabellen nicht einmal in information_schema), und die Fixtures raeumen
-- auf -> volle Rechte wie im Testschema-Block von provision.sql (~Zeile 654).
-- Der dortige `all tables`-Grant ist eine Momentaufnahme und erfasst neue
-- Tabellen nicht, darum hier ausdruecklich.
do $$
declare
  s text := current_setting('post.schema');
  rolle text;
  rechte text := 'select, insert, update';
  t text;
begin
  if s = 'sales' then
    rolle := 'sales_app';
  elsif s = 'sales_test' then
    rolle := 'sales_app';
    rechte := 'select, insert, update, delete, truncate';
  elsif exists (
      select 1 from pg_roles where rolname = 'sales_app_' || substr(s, 7)) then
    rolle := 'sales_app_' || substr(s, 7);
  end if;
  if rolle is null then
    -- Nicht still ueberspringen: ein Laden ohne Rolle haette sonst keine Rechte,
    -- und niemand wuerde es merken.
    raise notice 'WARNUNG: keine Rechte vergeben fuer Schema %: Rolle % existiert nicht', s, 'sales_app_' || substr(s, 7);
    return;
  end if;
  foreach t in array array['post_konten','post_mails','post_regeln',
      'post_abteilungen','post_abteilung_faecher','benutzer_abteilungen'] loop
    execute format('grant %s on %I.%I to %I', rechte, s, t, rolle);
  end loop;
end $$;


-- ---------------------------------------------------------------------------
-- Post-Einordnung v2 (Spec 2026-11-04-post-einordnung-v2-design.md). Alles
-- idempotent und auf Schemata mit Stufe-1-Daten anwendbar.
-- ---------------------------------------------------------------------------

-- Standardbereich je Konto: eine Mail aus dem Konto ist ohne anderen Hinweis
-- privat oder business. `business` als Vorgabe, weil bisher alles so lief; die
-- Konten aus der Umgebung behalten ihn (env_konten_uebernehmen setzt nichts).
alter table :"schema".post_konten
  add column if not exists standard_bereich text not null default 'business'
  check (standard_bereich in ('privat','business'));

-- Unterfach, Modell-Vorschlaege, Zaehler fuer Modellaufrufe (Kostenbremse),
-- Version der Einordnungslogik (fuer spaetere Neu-Einordnung) und die
-- zwischengespeicherte Vorschau.
alter table :"schema".post_mails
  add column if not exists unterfach text,
  add column if not exists vorschlaege jsonb,
  add column if not exists modellaufrufe smallint not null default 0,
  add column if not exists einordnung_version smallint not null default 1,
  add column if not exists vorschau jsonb,
  add column if not exists vorschau_am timestamptz,
  -- Kosten der Vorschau fuer die Tagesgrenze; bleibt, wenn anwenden die Vorschau leert.
  add column if not exists vorschau_aufrufe smallint not null default 0,
  -- Veraltet: ersetzt durch fehl_am (s. u.); die Spalte bleibt stehen, wird nicht mehr gelesen.
  add column if not exists versuch_am timestamptz,
  -- Kosten der Fehlversuche (Pruefer/Sortierer ausgefallen, Mail bleibt `neu`) mit Tagesreset
  -- ueber fehl_am: jeder Aufruf zaehlt genau einmal, an dem Tag, an dem er anfiel.
  -- `modellaufrufe` traegt nur noch die Kosten der endgueltigen Einordnung.
  add column if not exists fehl_aufrufe smallint not null default 0,
  add column if not exists fehl_am timestamptz;

alter table :"schema".post_regeln
  add column if not exists unterfach text;

-- Neue Quellen 'katalog' und 'pruefer'. Der alte Check ist inline angelegt und
-- hat von Postgres den Standardnamen <tabelle>_<spalte>_check bekommen. Ersetzt
-- wird nur, wenn er die neuen Werte noch nicht kennt - ein zweiter Lauf fasst
-- die Tabelle nicht erneut an.
do $$
declare
  s text := current_setting('post.schema');
begin
  if not exists (
      select 1 from pg_constraint c
      where c.conrelid = format('%I.post_mails', s)::regclass
        and c.conname = 'post_mails_einordnung_quelle_check'
        and pg_get_constraintdef(c.oid) like '%pruefer%') then
    execute format('alter table %I.post_mails drop constraint if exists '
                   'post_mails_einordnung_quelle_check', s);
    execute format('alter table %I.post_mails add constraint '
                   'post_mails_einordnung_quelle_check check '
                   '(einordnung_quelle in (''regel'',''modell'',''mensch'','
                   '''katalog'',''pruefer''))', s);
  end if;
end $$;

-- 'Unklar' heisst jetzt 'Zum Nachsehen' und gibt es nur noch privat: was nicht
-- einzuordnen ist, soll nie in einem Business-Fach untergehen (und damit auch
-- nicht fuer Abteilungen sichtbar werden).
update :"schema".post_mails set fach = 'Zum Nachsehen', bereich = 'privat'
  where fach = 'Unklar';
-- Regeln nach 'Unklar'/'Zum Nachsehen' sind sinnlos (dort entscheidet ein Mensch) und
-- braechen mit business die Privat-Regel oben. Der Code ueberspringt sie ohnehin
-- (post_einordnung.nach_nutzerregel); hier verschwinden auch die alten Zeilen.
delete from :"schema".post_regeln where fach in ('Unklar', 'Zum Nachsehen');

-- Neue Business-Faecher fuer die Abteilung Marketing.
insert into :"schema".post_abteilung_faecher (abteilung, fach) values
  ('Marketing', 'Veranstaltungen'),
  ('Marketing', 'Soziale Netzwerke')
  on conflict do nothing;


-- ---------------------------------------------------------------------------
-- Aufräumen (Spec 2026-11-06). Alles idempotent.
-- ---------------------------------------------------------------------------

-- Aufmerksamkeit, Ziel je Mail, Stand im Postfach-Ordner und Loeschzeitpunkt.
-- `ziel` ist das Soll, `ordner*` der zuletzt gemeldete Ist-Stand im Postfach.
-- `ziel_manuell` schuetzt eine Handentscheidung vor dem automatischen Neuberechnen.
alter table :"schema".post_mails
  add column if not exists aufmerksamkeit boolean,
  add column if not exists werbung_sicher boolean not null default false,
  add column if not exists ziel text
    check (ziel in ('posteingang','zur_info','to_review','loeschen')),
  add column if not exists ziel_manuell boolean not null default false,
  add column if not exists ordner text not null default 'INBOX',
  add column if not exists ordner_uid bigint,
  add column if not exists ordner_stand text
    check (ordner_stand in ('ok','fehlt','fehler')),
  add column if not exists ordner_am timestamptz,
  add column if not exists urspruengliche_adresse text,
  add column if not exists geloescht_am timestamptz;

-- Status 'geloescht' neu. Der Check ist inline angelegt und heisst
-- post_mails_status_check (in sales_test aus pg_constraint gelesen). Ersetzt
-- wird nur, wenn er den neuen Wert noch nicht kennt.
do $$
declare
  s text := current_setting('post.schema');
begin
  if not exists (
      select 1 from pg_constraint c
      where c.conrelid = format('%I.post_mails', s)::regclass
        and c.conname = 'post_mails_status_check'
        and pg_get_constraintdef(c.oid) like '%geloescht%') then
    execute format('alter table %I.post_mails drop constraint if exists '
                   'post_mails_status_check', s);
    execute format('alter table %I.post_mails add constraint '
                   'post_mails_status_check check '
                   '(status in (''neu'',''eingeordnet'',''fehler'',''geloescht''))', s);
  end if;
end $$;

-- NULL = Verschieben und Loeschen sind aktiv; sonst steht hier der Grund fuer die Ruhe.
alter table :"schema".post_konten
  add column if not exists ordnen_aus text;

-- 'nie_werbung': Absender, die nie als Werbung (und damit nie zum Loeschen) gelten.
alter table :"schema".post_regeln
  add column if not exists art text not null default 'einordnen'
    check (art in ('einordnen','nie_werbung'));

-- Freigabe zum Loeschen je Besitzer und Jahr; `ausgenommen` haelt einzelne Mails heraus.
create table if not exists :"schema".post_loeschfreigaben (
  id uuid primary key default gen_random_uuid(),
  besitzer text not null,
  jahr int not null,
  freigegeben_am timestamptz not null default now(),
  ausgenommen jsonb not null default '[]',
  unique (besitzer, jahr)
);

create index if not exists post_mails_ziel_ordner_idx
  on :"schema".post_mails (ziel, ordner);

-- Rechte fuer die neue Tabelle (der Block oben kennt sie nicht), gleiche Regeln.
do $$
declare
  s text := current_setting('post.schema');
  rolle text;
  rechte text := 'select, insert, update';
begin
  if s = 'sales' then
    rolle := 'sales_app';
  elsif s = 'sales_test' then
    rolle := 'sales_app';
    rechte := 'select, insert, update, delete, truncate';
  elsif exists (
      select 1 from pg_roles where rolname = 'sales_app_' || substr(s, 7)) then
    rolle := 'sales_app_' || substr(s, 7);
  end if;
  if rolle is null then
    raise notice 'WARNUNG: keine Rechte vergeben fuer Schema %: Rolle % existiert nicht', s, 'sales_app_' || substr(s, 7);
    return;
  end if;
  execute format('grant %s on %I.post_loeschfreigaben to %I', rechte, s, rolle);
end $$;
