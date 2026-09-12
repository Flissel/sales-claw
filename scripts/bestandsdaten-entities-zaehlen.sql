-- scripts/bestandsdaten-entities-zaehlen.sql
--
-- NUR LESEND. Zaehlt, wie viele Bestandsdaten HTML-Entities im Klartext
-- tragen ("&amp;" statt "&"). Kein UPDATE, kein DELETE, kein BEGIN — die
-- Datei kann gefahrlos gegen Produktion laufen.
--
-- WOZU
-- Der Lesepfad ist seit Stufe 1 korrekt (kalender._ics_feld loest das
-- ICS-Escaping jetzt auf). Die ALTEN Eintraege sind es nicht. Die Anzeige
-- wird dadurch ehrlich, aber nicht schoen: wo frueher "&amp;amp\;" stand,
-- steht jetzt sichtbar "&amp;". Diese Datei liefert die Zahl, mit der sich
-- entscheiden laesst, ob eine Bereinigung sich lohnt — sie bereinigt nichts.
--
-- Wer den escapeten Text urspruenglich geschrieben hat, ist geklaert: er
-- kommt als Werkzeug-Argument von aussen, also vom aufrufenden Sprachmodell.
-- Keine Code-Stelle escapet beim Speichern. Eine Abwehr im Schreibpfad waere
-- eine Produktentscheidung mit Nebenwirkung (ein Kunde, der woertlich
-- "&amp;" schreibt, wuerde stillschweigend umgeschrieben) — deshalb bewusst
-- offen gelassen.
--
-- WARUM DIE MUSTER "\\*" ENTHALTEN (gemessen 12.09.2026, nicht vermutet)
-- Die ICS-maskierte Form ist "&amp\;" mit EINEM Backslash. In einer
-- jsonb-Spalte kann sie nicht anders liegen: "\;" ist kein gueltiges
-- JSON-Escape, Postgres lehnt es beim Schreiben ab
-- ("Escape sequence \; is invalid"). Die Quelle muss also "\\;" schreiben,
-- gespeichert wird EIN Backslash — und payload::text gibt ihn VERDOPPELT
-- zurueck:
--
--   Feldwert   (payload->>'thema')  ->  Angebot &amp\;Vertrag
--   Textform   (payload::text)      ->  {"thema": "Angebot &amp\\;Vertrag"}
--   Muster \\? auf der Textform     ->  f   <- findet es NICHT
--   Muster \\* auf der Textform     ->  t
--
-- Ein Muster mit "\\?" haette also ausgerechnet die Eintraege uebersehen,
-- derentwegen diese Datei existiert. Wer die Muster aendert, misst das bitte
-- nach, statt es zu ueberlegen.
--
-- AUFRUF (Muster aus docs/03_RUNBOOK.md, Abschnitt "psql-Gegenproben")
-- Die DSN gehoert NIE in eine Kommandozeile — sie stuende in der
-- Prozessliste des Hosts. Deshalb: als Host-Variable setzen, OHNE Wert
-- durchreichen, erst in der Container-Shell aufloesen.
-- Es gibt keinen Postgres-Container im Stack; die Datenbank liegt ausserhalb.
--
--   export SALES_DSN=$(grep '^SALES_DB_URL=' .env | sed 's/^SALES_DB_URL=//')
--   docker run --rm -e SALES_DSN -i postgres:17-alpine \
--     sh -c 'psql "$SALES_DSN" -f -' \
--     < scripts/bestandsdaten-entities-zaehlen.sql
--   unset SALES_DSN
--
-- Gegen das Testschema zusaetzlich: sh -c 'psql "$SALES_DSN" -v schema=sales_test -f -'

-- Ohne -v schema=... gilt das Produktionsschema.
\if :{?schema}
\else
  \set schema sales
\endif

set search_path to :"schema";

\echo ''
\echo '=== 1. Betroffene Zeilen je Feld ==='
\echo ''

with alle as (
  select 'leads.name'         as feld, name           as inhalt, created_at from leads
  union all
  select 'leads.company',           company,                     created_at from leads
  union all
  select 'leads.title',             title,                       created_at from leads
  union all
  select 'leads.notes',             notes,                       created_at from leads
  union all
  select 'activities.payload',      payload::text,               created_at from activities
  union all
  select 'drafts.subject',          subject,                     created_at from drafts
  union all
  select 'drafts.body',             body,                        created_at from drafts
)
select feld,
       count(*)                                                                       as zeilen,
       count(*) filter (where inhalt ~ '&amp;(amp|lt|gt|quot|apos|#x27|#39)\\*;')     as davon_doppelt,
       -- Bewusst NICHT an eine Entity gebunden: "&amp;amp\;" traegt den
       -- Backslash hinter der ZWEITEN Entity, ein an "&amp" verankertes
       -- Muster haette diese Zeile uebersehen und damit eine Spalte gehabt,
       -- die weniger zaehlt als ihr Name verspricht. Gefragt ist hier nur:
       -- steckt irgendwo ein ICS-maskiertes Semikolon drin?
       count(*) filter (where inhalt ~ '\\+;')                                        as davon_ics_maskiert,
       min(created_at)::date                                                          as aeltester,
       max(created_at)::date                                                          as juengster
from alle
where inhalt ~ '&(amp|lt|gt|quot|apos|#x27|#39)\\*;'
group by feld
order by zeilen desc;

\echo ''
\echo '=== 2. Welche Aktivitaetsarten sind betroffen? ==='
\echo ''

select type                                                                           as art,
       count(*)                                                                       as zeilen,
       min(created_at)::date                                                          as aeltester,
       max(created_at)::date                                                          as juengster
from activities
where payload::text ~ '&(amp|lt|gt|quot|apos|#x27|#39)\\*;'
group by type
order by count(*) desc;

\echo ''
\echo '=== 3. Beispiele zum Ansehen (hoechstens 15) ==='
\echo ''

select created_at::date                                                               as datum,
       type                                                                           as art,
       left(payload::text, 160)                                                       as ausschnitt
from activities
where payload::text ~ '&(amp|lt|gt|quot|apos|#x27|#39)\\*;'
order by created_at desc
limit 15;

\echo ''
\echo '=== 4. Gesamtbestand zum Vergleich ==='
\echo ''

select 'leads'      as tabelle, count(*) as zeilen from leads
union all
select 'activities',            count(*)           from activities
union all
select 'drafts',                count(*)           from drafts;

\echo ''
\echo 'Nichts geaendert — diese Datei liest nur.'
\echo ''
