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

  -- pg_trgm muss IM SCHEMA `extensions` liegen, nicht irgendwo. Grund
  -- (gemessen 17.09.2026): die Dienste verbinden mit
  -- `search_path=<laden>,extensions`; liegt die Erweiterung in `public`,
  -- ist `similarity()` zur Laufzeit unerreichbar (42883) - waehrend das
  -- Anlegen des Index hier gelingt, weil psql mit anderem Suchpfad laeuft.
  -- Genau diese Kombination ist ein stiller Ausfall: Schema gruen,
  -- Werkzeug tot. Deshalb prueft die Wache das Schema MIT.
  if not exists (
        select 1 from pg_extension e
          join pg_namespace n on n.oid = e.extnamespace
         where e.extname = 'pg_trgm' and n.nspname = 'extensions') then
    raise exception 'Extension "pg_trgm" fehlt oder liegt nicht in "extensions". Als Admin: create extension pg_trgm with schema extensions; -- bzw. alter extension pg_trgm set schema extensions;';
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
-- Ohne DIESE Zeile ist `kontakt_aehnlich` tot, und zwar lautlos: die
-- Erweiterung `pg_trgm` liegt in `extensions`, der Suchpfad der Dienste
-- fuehrt das Schema mit — aber ohne USAGE darauf findet die Rolle
-- `similarity()` trotzdem nicht (42883). Gemessen am 17.09.2026 NACH einem
-- gruenen Deploy: Code richtig, Suchpfad richtig, Index da, Werkzeug tot.
-- `has_schema_privilege('sales_app','extensions','usage')` war `false`.
grant usage on schema extensions to sales_app;
grant usage on schema sales to sales_app;
grant usage on schema sales_test to sales_app;

-- Identische Tabellen in JEDEM Laden-Schema; nur die Rechte unterscheiden
-- sich (sales_test: siehe GRANT-Block unten). Schlussprüfung K3
-- (16.09.2026): bis dahin stand hier ein Literal, `array['sales',
-- 'sales_test']` — jede kuenftige Schemaaenderung haette jeden WEITEREN
-- Laden (sales_ivan, ...) stumm uebersprungen. Gemessen: in der
-- Testdatenbank fehlten sales_probe/sales_pruef die vier reset_*-Spalten
-- aus einem frueheren Commit; auf der Produktion war sales_ivan im selben
-- Zustand.
--
-- Jetzt wird ueber die TATSAECHLICH vorhandenen Laden-Schemata geschleift
-- — dasselbe Muster wie server.py:SCHEMA_MUSTER
-- (`sales(_[a-z][a-z0-9_]{0,30})?`), das definiert, was ueberhaupt ein
-- gueltiger Laden-Schemaname ist. Ein Schema, das nur zufaellig mit
-- "sales" beginnt aber nicht auf dieses Muster passt (oder gar nicht erst
-- als Laden-Schema angelegt wurde), wird NICHT erfasst. `sales` und
-- `sales_test` existieren zu diesem Zeitpunkt bereits (zwei Zeilen oben
-- angelegt, in DERSELBEN Session sichtbar) und werden deshalb automatisch
-- mit erfasst, ohne eigenen Sonderfall.
do $$
declare s text;
declare laeden text[];
begin
  select coalesce(array_agg(schema_name order by schema_name), array[]::text[])
    into laeden
    from information_schema.schemata
    where schema_name ~ '^sales(_[a-z][a-z0-9_]{0,30})?$';
  foreach s in array laeden loop
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
    -- Rolle 'kalender' (12.09.2026): schmaler Zugang fuer einen Kollegen,
    -- der nur seinen Kalender verbindet — sieht NICHT, was 'lesen' sieht
    -- (Kontakte, Entwuerfe, Posteingang), siehe ui._pfad_erlaubt.
    execute format($ddl$
      create table if not exists %I.benutzer (
        name text primary key check (name !~ '[|:]' and name <> ''),
        rolle text not null check (rolle in ('lesen','freigeben','kalender')),
        passwort_hash text not null,
        aktiv boolean not null default true,
        created_at timestamptz not null default now()
      )$ddl$, s);
    -- Rolle 'kalender' nachtraeglich zugelassen (Fix-Runde Schlusspruefung,
    -- 13.09.2026): auf bereits bestehenden Installationen (`benutzer` steht
    -- seit E1, 31.08.2026) wirkt das obige `create table if not exists`
    -- nicht mehr, der alte Zwei-Werte-CHECK ueberlebt und
    -- `benutzer_anlegen.py` scheitert mit 23514. Per ALTER nachgezogen,
    -- idempotent wie beim drafts_channel_check-Muster unten.
    execute format('alter table %I.benutzer drop constraint if exists benutzer_rolle_check', s);
    execute format($chk$alter table %I.benutzer add constraint benutzer_rolle_check
      check (rolle in ('lesen','freigeben','kalender'))$chk$, s);
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
    -- Abonnierte Fremdkalender (Spec 2026-09-11 §2.1 Weg 3, ergaenzt
    -- 12.09.2026). `url` ist die GEHEIME iCal-Adresse eines Kollegen und
    -- damit ein Geheimnis mit der Berechtigung darin: wer sie kennt, liest
    -- den Kalender. Sie wird nie angezeigt und nie geloggt (Spec §4).
    -- `art` ist heute nur 'ics'; der eigene CalDAV-Kalender bleibt in der
    -- .env, weil er Zugangsdaten braucht und genau einer ist.
    -- `url` darf null sein (Fix-Runde 2, 13.09.2026): `sales_app` hat auf
    -- keiner Tabelle ein DELETE-Recht, dieses Projekt macht dafuer keine
    -- Ausnahme (Gegen-Ereignis statt Loeschung, wie ueberall im Haus).
    -- kalenderquelle_entfernen() deaktiviert die Zeile stattdessen (aktiv
    -- = false) und vernichtet dabei die Adresse (url = null) — leer darf
    -- sie trotzdem nie sein, nur fehlend.
    execute format($ddl$
      create table if not exists %I.kalender_quellen (
        id uuid primary key default gen_random_uuid(),
        anzeigename text not null check (anzeigename <> ''),
        art text not null default 'ics' check (art in ('ics')),
        url text check (url is null or url <> ''),
        aktiv boolean not null default true,
        zuletzt_gelesen timestamptz,
        letzter_fehler text,
        termine_zuletzt int,
        created_at timestamptz not null default now()
      )$ddl$, s);
    execute format('create unique index if not exists '
                   'kalender_quellen_name_idx on %I.kalender_quellen '
                   '(anzeigename)', s);
    -- `url` nachtraeglich nullbar gemacht (Fix-Runde 2, 13.09.2026): auf
    -- bereits bestehenden Installationen wirkt das obige `create table if
    -- not exists` nicht mehr, deshalb per ALTER nachgezogen; idempotent
    -- wie beim drafts_channel_check-Muster darunter.
    execute format('alter table %I.kalender_quellen alter column url drop not null', s);
    execute format('alter table %I.kalender_quellen drop constraint if exists kalender_quellen_url_check', s);
    execute format($chk$alter table %I.kalender_quellen add constraint kalender_quellen_url_check
      check (url is null or url <> '')$chk$, s);
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

    -- Passwort-Vergessen (16.09.2026): eine Adresse, an die ein Einmal-Link
    -- gehen kann, und der Token selbst — GEHASHT, nie im Klartext. Wer die
    -- Datenbank liest, darf damit kein Konto uebernehmen koennen; dieselbe
    -- Ueberlegung wie beim passwort_hash daneben.
    --
    -- Warum ueberhaupt: `benutzer_anlegen.py` setzt Passwoerter per
    -- Kommandozeile im Container, und das kann nur, wer eine Shell auf der
    -- VM hat. Der zweite Benutzer (Rolle `kalender`) hat die nicht - fuer
    -- ihn war Aussperrung bisher endgueltig.
    execute format('alter table %I.benutzer add column if not exists email text', s);
    execute format('alter table %I.benutzer add column if not exists reset_hash text', s);
    execute format('alter table %I.benutzer add column if not exists reset_bis timestamptz', s);
    -- Eine Bremse gegen Mailfluten auf Zuruf: wann zuletzt ein Link ging.
    execute format('alter table %I.benutzer add column if not exists reset_zuletzt timestamptz', s);

    -- Auftragszettel fuer Mails AN DAS EIGENE HAUS (17.09.2026).
    --
    -- WARUM ES DIESE TABELLE GIBT: die Oberflaeche kann nicht selbst
    -- senden - und soll es nicht koennen. Nach T5a (Stufe 3) liegt
    -- Sendemacht ausschliesslich bei den Versand-Diensten, damit das
    -- Freigabe-Tor die DATENBANK bleibt und nicht die Exec-Freigabeliste
    -- des Docker-Hosts. `sales-ui` hat deshalb keine SMTP-Zugangsdaten,
    -- und der erste Anlauf des Passwort-Vergessens scheiterte genau daran:
    -- die Route rief `mail_dispatch.senden` im UI-Container auf, der
    -- Import gelang (dasselbe Image), der Versand konnte nie gelingen.
    --
    -- Also dieselbe Bruecke wie `marketing.versandauftraege`: wer nicht
    -- senden darf, legt einen Zettel; wer senden darf, holt ihn ab.
    --
    -- WAS HIER NICHT DRINSTEHT: der Token. Den erzeugt der VERSENDER,
    -- unmittelbar bevor er die Mail baut, und schreibt nur dessen Hash
    -- nach `benutzer.reset_hash`. Der Klartext erreicht die Datenbank
    -- also nie - auch nicht fuer die Sekunden, die ein Zettel hier liegt.
    execute format($t$create table if not exists %I.benutzer_mails (
        id uuid primary key default gen_random_uuid(),
        benutzer text not null,
        art text not null check (art in ('passwort_reset')),
        status text not null default 'offen'
               check (status in ('offen','gesendet','fehler')),
        grund text not null default '',
        erstellt_am timestamptz not null default now(),
        erledigt_am timestamptz)$t$, s);
    execute format('create index if not exists benutzer_mails_offen_idx '
                   'on %I.benutzer_mails (status, erstellt_am)', s);
    execute format('create index if not exists leads_status_idx on %I.leads (status)', s);

    -- Aehnlichkeitssuche ueber Namen (17.09.2026), Trigramme.
    --
    -- WOFUER: Dubletten und Schreibvarianten, die ein exakter Vergleich nie
    -- findet. Gemessen am selben Tag am echten Bestand: „Webdesigner
    -- Muenchen" ~ „Webdesign Muenchen" (0.81), „DataGuard - Datenschutz &
    -- Informationssicherheit" ~ „DATENSCHUTZ UND INFORMATIONSSICHERHEIT"
    -- (0.76). Beide haben VERSCHIEDENE Nummern und werden von der
    -- Nummern-Dedup in `kontakt_anlegen` zu Recht nicht erfasst - die
    -- prueft Identitaet, nicht Aehnlichkeit.
    --
    -- WOFUER NICHT: als Dublettenbeweis. Ein Trigramm-Fund sagt „die beiden
    -- sehen sich aehnlich", nicht „hier ist ein Fehler" - „Ark Software
    -- GmbH" ~ „SMC Software GmbH" (0.67) sind verschiedene Firmen. Deshalb
    -- gibt das Werkzeug die Naehe MIT aus und entscheidet nicht selbst.
    --
    -- Auch eine belastbare NEGATIVaussage wird damit moeglich:
    -- `similarity(name,'Ivan') > 0.3` lieferte genau einen Treffer - „Iwan"
    -- oder „Ivan G." haette es gefunden.
    execute format('create index if not exists leads_name_trgm_idx '
                   'on %I.leads using gin (name extensions.gin_trgm_ops)', s);
    execute format('create index if not exists activities_lead_idx on %I.activities (lead_id, created_at desc)', s);

    -- Volltextsuche ueber den Gespraechsverlauf (22.09.2026), deutsch.
    --
    -- NUR DREI SCHLUESSEL, und das ist Absicht: gemessen am 17.09. tragen
    -- `text` (3005), `inhalt` (888) und `begruendung` (141) Freitext,
    -- waehrend `message_id` (6155!), `draft_id` und `lead_id` Kennungen
    -- sind. Kennungen in einem Volltextindex verwaessern jede Frage - sie
    -- erzeugen Treffer, die nur zufaellig Zeichen teilen.
    --
    -- Erzeugte Spalte statt Index-Ausdruck, damit `ts_headline` und
    -- `ts_rank` denselben Text sehen wie der Index - ein Ausdrucksindex
    -- waere bei jeder Abfrage neu zu tippen und irgendwann anders.
    --
    -- ZWEI GEMESSENE GRENZEN, die der Werkzeug-Hinweis wiederholt:
    --   * Der deutsche Stemmer trennt Substantiv und Verb. „Nummer
    --     gewechselt" findet den Satz „Falscher Ivan hat Nummer WECHSEL
    --     gehabt" NICHT (0 Treffer, gemessen 17.09.2026).
    --   * Verneinung wird ignoriert: „kein Interesse" liefert lauter
    --     Interessenten.
    -- Das ist keine Schwaeche dieser Umsetzung, sondern wie Volltextsuche
    -- arbeitet - und deshalb steht es dort, wo jemand es liest.
    execute format($t$alter table %I.activities
        add column if not exists suchtext tsvector
        generated always as (to_tsvector('german'::regconfig,
            coalesce(payload->>'text', '') || ' ' ||
            coalesce(payload->>'inhalt', '') || ' ' ||
            coalesce(payload->>'begruendung', ''))) stored$t$, s);
    execute format('create index if not exists activities_suchtext_idx '
                   'on %I.activities using gin (suchtext)', s);
    execute format('create index if not exists drafts_status_idx on %I.drafts (status, created_at desc)', s);
  end loop;
end $$;

-- updated_at-Pflege, Eigentümer supabase_admin. Derselbe K3-Befund galt
-- hier genauso (zwei fest verdrahtete Schemata statt der tatsaechlich
-- vorhandenen) — ohne diesen Nachzug bekaeme jeder WEITERE Laden nie eine
-- funktionierende updated_at-Pflege auf `leads`. Dieselbe Ermittlung der
-- Laden-Schemata wie im Tabellen-Block oben, ein zweites Mal, weil
-- PL/pgSQL-`do`-Bloecke keine gemeinsame Variable teilen.
do $$
declare s text;
declare laeden text[];
begin
  select coalesce(array_agg(schema_name order by schema_name), array[]::text[])
    into laeden
    from information_schema.schemata
    where schema_name ~ '^sales(_[a-z][a-z0-9_]{0,30})?$';
  foreach s in array laeden loop
    execute format($crt$create or replace function %I.set_updated_at()
      returns trigger language plpgsql as
      $body$ begin new.updated_at = now(); return new; end; $body$ $crt$, s);
    execute format('drop trigger if exists leads_updated_at on %I.leads', s);
    execute format('create trigger leads_updated_at before update on %I.leads '
                    'for each row execute function %I.set_updated_at()', s, s);
  end loop;
end $$;

-- Auftraege "Laden anlegen" aus der Oberflaeche (22.09.2026).
--
-- ANDERS ALS DER TABELLEN-BLOCK OBEN: diese Tabelle gehoert NICHT zu jedem
-- Laden, sondern ausschliesslich dem Basis-Laden — dieselbe Ueberlegung wie
-- compliance/compliance_test, NICHT wie K3 (dort war "zwei feste Schemata"
-- der Fehler, weil die betroffenen Tabellen in JEDEM Laden gebraucht
-- wurden; hier ist "zwei feste Schemata" richtig, weil die Faehigkeit
-- ausdruecklich nur dem Basis-Laden gehoert). sales_test steht daneben,
-- damit die Testsuite (die NIE gegen sales laufen darf) die Rollen-
-- Tor-Logik und den Einfuege-/Anzeige-Pfad ueberhaupt pruefen kann.
do $$
declare s text;
begin
  foreach s in array array['sales','sales_test'] loop
    execute format($t$create table if not exists %I.admin_auftraege (
        id uuid primary key default gen_random_uuid(),
        art text not null check (art = 'laden_anlegen'),
        name text not null check (name ~ '^[a-z][a-z0-9_]{0,30}$'),
        angefordert_von text not null,
        status text not null default 'offen'
               check (status in ('offen','laeuft','erfolg','fehler')),
        ergebnis jsonb,
        fehler text,
        erstellt_am timestamptz not null default now(),
        erledigt_am timestamptz)$t$, s);
    execute format('create index if not exists admin_auftraege_offen_idx '
                   'on %I.admin_auftraege (status, erstellt_am)', s);
  end loop;
end $$;

-- Rechte Demo-Schema: activities append-only als Datenbank-Garantie.
grant select, insert, update on sales.leads    to sales_app;
grant select, insert         on sales.activities to sales_app;
grant select, insert, update on sales.drafts   to sales_app;
grant select, insert, update on sales.personas to sales_app;
grant select, insert, update on sales.benutzer to sales_app;
grant select, insert, update on sales.benutzer_mails to sales_app;
-- Kein update, kein delete: die Oberflaeche legt einen Auftrag an, sie
-- aendert ihn nie wieder — nur der Wirt (als supabase_admin) tut das.
grant select, insert on sales.admin_auftraege to sales_app;
grant select, insert, update on sales.medien_meta to sales_app;
grant select, insert, update on sales.kalender_quellen to sales_app;
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
