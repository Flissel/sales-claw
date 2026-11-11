-- compliance_test — Verbotsliste NUR fuer sales-claws Testlaeufe.
-- Aufruf nach db/provision.sql (die Rolle sales_app muss existieren):
--
--   psql -v ON_ERROR_STOP=1 -f db/compliance-test.sql
--
-- Herkunft: Marketing-Migration 013b_compliance_test_schema.sql (03.09.2026).
-- Sie liegt in vibemind-os nur auf dem Sicherungsbranch
-- codex/backup-pre-origin-sync-20260825 (0eedb8bf), nie auf master; auf der
-- VM wurde das Schema damals von Hand angelegt. Die CI braucht sie trotzdem:
-- sales-mcp/sperrliste.py waehlt bei SALES_DB_SCHEMA=sales_test dieses Schema,
-- ohne es scheitern Kontakt- und Entwurfswerkzeuge an
-- `schema "compliance_test" does not exist`.
--
-- Gleiche DDL wie die Produktionsliste compliance.sperrliste (Marketing-
-- Migration 013), OHNE Marketing-Trigger und ohne Bestandsuebernahme. Die
-- Produktionsliste gehoert weiter dem Marketing-Space; aendert sich dort die
-- DDL, muss diese Kopie mitziehen. Idempotent.
\set ON_ERROR_STOP on

create schema if not exists compliance_test;

create table if not exists compliance_test.sperrliste (
    kennung          text primary key,
    quelle           text not null,
    grund            text not null default '',
    seit             timestamptz not null default now(),
    aufgehoben_am    timestamptz,
    aufgehoben_grund text,
    constraint kennung_form check (kennung ~ '^(email:[^A-Z\s]+|tel:\+[0-9]{6,})$')
);

create or replace function compliance_test.sperren(p_kennung text, p_quelle text, p_grund text)
returns void language sql as $$
    insert into compliance_test.sperrliste (kennung, quelle, grund)
    values (p_kennung, p_quelle, coalesce(p_grund, ''))
    on conflict (kennung) do update
        set quelle = excluded.quelle, grund = excluded.grund, seit = now(),
            aufgehoben_am = null, aufgehoben_grund = null
        where compliance_test.sperrliste.aufgehoben_am is not null;
$$;

create or replace function compliance_test.ist_gesperrt(p_kennung text)
returns text language sql stable as $$
    select quelle || ': ' || grund from compliance_test.sperrliste
    where kennung = p_kennung and aufgehoben_am is null;
$$;

-- Testlaeufe duerfen hier auch aufraeumen (TRUNCATE), anders als in compliance.
grant usage on schema compliance_test to sales_app;
grant select, insert, update, delete, truncate on compliance_test.sperrliste to sales_app;
grant execute on function compliance_test.sperren(text, text, text) to sales_app;
grant execute on function compliance_test.ist_gesperrt(text) to sales_app;
