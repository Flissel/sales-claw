-- Minimaler Ersatz fuer das Auftragsbuch (Schema `auftrag`), NUR fuer test_video_uebergabe_sql.py.
-- Namen und Signaturen wie in vibemind-os spaces/marketing/db/096_auftragsbuch.sql und 098_auftragsbuch_video.sql
-- (Auszug): Tabelle auftrag.auftraege und Funktion auftrag.sales_anlegen(p_an, p_laden, p_mandant, p_art, p_eingabe,
-- p_eltern) mit denselben Pruefungen und demselben Wortlaut der Fehler (RAISE EXCEPTION -> SQLSTATE P0001), darunter die
-- Tagesgrenze "hoechstens 2 Video-Auftraege je Laden pro Tag". Der Test schaltet das Verhalten ueber auftrag.test_modus:
--   ok | ablehnung (P0001, allgemein) | rechte (42501) | ausfall_nach_insert (Division durch null nach dem Insert).
-- Die Datei wird nur ausgefuehrt, wenn das Schema `auftrag` NICHT existiert (oder dieser Marke traegt); ein echtes
-- Auftragsbuch wird nie angefasst. Der Test legt das Schema an und wirft es am Ende wieder weg.
create schema auftrag;
comment on schema auftrag is 'TEST-STANDIN fuer video_uebergabe (kein echtes Auftragsbuch)';

create table auftrag.auftraege (
  id uuid primary key default gen_random_uuid(),
  von text not null,
  an text not null,
  laden text not null,
  mandant text not null,
  art text not null,
  eingabe jsonb not null default '{}'::jsonb,
  angelegt timestamptz not null default now()
);

create table auftrag.test_modus (modus text not null);
insert into auftrag.test_modus values ('ok');

create function auftrag.sales_anlegen(p_an text, p_laden text, p_mandant text, p_art text,
    p_eingabe jsonb, p_eltern uuid default null) returns uuid
language plpgsql as $$
declare
  v_id uuid := gen_random_uuid();
  v_n int;
  v_modus text;
begin
  select modus into v_modus from auftrag.test_modus limit 1;
  if v_modus = 'rechte' then
    raise exception 'permission denied for function sales_anlegen' using errcode = '42501';
  end if;
  if v_modus = 'ablehnung' then
    raise exception 'Unbekannte Art des Auftrags';
  end if;
  if p_an is distinct from 'marketing' then
    raise exception 'Sales darf Auftraege nur an Marketing geben';
  end if;
  if coalesce(btrim(p_laden), '') = '' or coalesce(btrim(p_mandant), '') = '' then
    raise exception 'Auftrag braucht Laden und Mandant';
  end if;
  perform pg_advisory_xact_lock(hashtext('auftrag:sales'));
  if p_art = 'video' then
    select count(*) into v_n from auftrag.auftraege
     where von = 'sales' and laden = p_laden and art = 'video'
       and (angelegt at time zone 'Europe/Berlin')::date = (now() at time zone 'Europe/Berlin')::date;
    if v_n >= 2 then
      raise exception 'Tagesgrenze erreicht: hoechstens 2 Video-Auftraege je Laden pro Tag';
    end if;
  end if;
  insert into auftrag.auftraege (id, von, an, laden, mandant, art, eingabe)
  values (v_id, 'sales', p_an, p_laden, p_mandant, p_art, coalesce(p_eingabe, '{}'::jsonb));
  if v_modus = 'ausfall_nach_insert' then
    perform 1 / 0;
  end if;
  return v_id;
end $$;
