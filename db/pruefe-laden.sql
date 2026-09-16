-- Haelt die Trennung? Aufruf MIT DER KENNUNG DES NEUEN LADENS:
--
--   psql "postgresql://sales_app_ivan:...@.../postgres" \
--        -v laden=ivan -f db/pruefe-laden.sql
--
-- Der entscheidende Unterschied, den dieses Skript pruefen soll:
-- "permission denied" ist etwas anderes als "leeres Ergebnis". Ein leeres
-- Ergebnis hiesse, die Zeilen sind nur gerade nicht da.
\set ON_ERROR_STOP off

\set schema 'sales_':laden

\echo '=== 1. Der eigene Laden ist lesbar (muss eine Zahl liefern) ==='
select count(*) as eigene_leads from :"schema".leads;

\echo ''
\echo '=== 2. Der fremde Laden ist es NICHT (muss permission denied sagen) ==='
select count(*) as fremde_leads from sales.leads;

\echo ''
\echo '=== 3. Die gemeinsame Sperrliste ist lesbar ==='
select count(*) as sperrliste from compliance.sperrliste;

\echo ''
\echo '=== 4. Kein DELETE, auch nicht im eigenen Laden ==='
delete from :"schema".leads where false;

\echo ''
\echo 'ERWARTET: 1 Zahl, 2 permission denied, 3 Zahl, 4 permission denied.'
\echo 'Liefert 2 eine Zahl — auch die 0 —, ist die Trennung GEBROCHEN.'
