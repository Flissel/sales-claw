import { describe, expect, it } from 'vitest';

import { braucheBestaetigung, type Ereignis, FARBEN, isoMitOffset, NICHT_IM_HANDY, zuAenderung, zuEvent } from './abbild';

const kunde: Ereignis = {
  id: 'kunde:abc', art: 'kunde', uid: 'abc', titel: 'Erstgespräch – Müller GmbH',
  beginn: '2026-10-20T10:00:00+02:00', ende: '2026-10-20T10:30:00+02:00',
  bearbeitbar: true, lead_id: '11111111-1111-1111-1111-111111111111', kontakt: 'Müller GmbH', ort: 'Büro',
};
const eigen: Ereignis = {
  id: 'eigen:x@sales-claw', art: 'eigen', uid: 'x@sales-claw', titel: 'Zahnarzt',
  beginn: '2026-10-21T08:00:00+02:00', ende: '2026-10-21T09:00:00+02:00',
  bearbeitbar: true, geaendert_am: '2026-10-14T09:00:00+00:00', notiz: 'Karte mitnehmen',
};
const handy: Ereignis = {
  id: 'handy:h1', art: 'handy', titel: 'Privat',
  beginn: '2026-10-22T12:00:00+02:00', ende: '2026-10-22T13:00:00+02:00', bearbeitbar: false,
};
const kollege: Ereignis = {
  id: 'kollege:k1', art: 'kollege', titel: 'Messe',
  beginn: '2026-10-22T12:00:00+02:00', ende: '2026-10-22T18:00:00+02:00', bearbeitbar: false, quelle: 'Anna',
};

describe('zuEvent', () => {
  it('Kunde ist ziehbar und traegt den Kontakt im Titel', () => {
    const ev = zuEvent(kunde);
    expect(ev.editable).toBe(true);
    expect(ev.title).toContain('Müller GmbH');
    expect(ev.id).toBe('kunde:abc');
    expect(ev.start).toBe(kunde.beginn);
    expect(ev.end).toBe(kunde.ende);
    expect(ev.color).toBe(FARBEN.kunde);
    expect(ev.extendedProps).toMatchObject({
      art: 'kunde', uid: 'abc', lead_id: kunde.lead_id, kontakt: 'Müller GmbH', ort: 'Büro', thema: 'Erstgespräch',
    });
  });

  it('Kunde ohne Kontakt im Titel bekommt ihn angehaengt', () => {
    expect(zuEvent({ ...kunde, titel: 'Erstgespräch' }).title).toBe('Erstgespräch – Müller GmbH');
  });

  it('Handy und Kollege sind nicht editable', () => {
    expect(zuEvent(handy).editable).toBe(false);
    expect(zuEvent(kollege).editable).toBe(false);
    expect(zuEvent(handy).color).toBe('#9ca3af');
    expect(zuEvent(kollege).color).toBe('#4d7c5a');
  });

  it('Kunde ohne Kontakt (bearbeitbar false) ist nicht editable', () => {
    expect(zuEvent({ ...kunde, bearbeitbar: false }).editable).toBe(false);
  });

  it('die Rolle ohne Schreibrecht ergibt editable false fuer alle', () => {
    for (const e of [kunde, eigen, handy, kollege]) expect(zuEvent(e, false).editable).toBe(false);
  });

  it('eigener Termin traegt Notiz und Stempel', () => {
    const ev = zuEvent(eigen);
    expect(ev.editable).toBe(true);
    expect(ev.color).toBe('#2563eb');
    expect(ev.extendedProps).toMatchObject({ art: 'eigen', notiz: 'Karte mitnehmen', geaendert_am: eigen.geaendert_am });
  });

  it('fehlgeschlagener Handy-Abgleich wird markiert, NULL nicht', () => {
    const fehl = zuEvent({ ...eigen, kalender_stand: 'fehlgeschlagen: 503' });
    expect(fehl.extendedProps?.handy_fehlt).toBe(true);
    expect(String(fehl.title)).toContain(NICHT_IM_HANDY);
    expect(zuEvent({ ...eigen, kalender_stand: null }).extendedProps?.handy_fehlt).toBe(false);
    expect(zuEvent({ ...eigen, kalender_stand: 'eingetragen' }).extendedProps?.handy_fehlt).toBe(false);
  });
});

describe('zuAenderung', () => {
  it('Ziehen um +60 min behaelt die Dauer', () => {
    const r = zuAenderung({ start: new Date(2026, 9, 20, 11, 0), end: new Date(2026, 9, 20, 11, 30) });
    expect(r).toEqual({ beginn: '2026-10-20T11:00:00+02:00', dauer_minuten: 30 });
  });

  it('Resize von 30 auf 90 ergibt 90', () => {
    const r = zuAenderung({ start: new Date(2026, 9, 20, 10, 0), end: new Date(2026, 9, 20, 11, 30) });
    expect(r.dauer_minuten).toBe(90);
  });

  it('ueber die Sommerzeit-Umstellung bleibt 14:00 lokal 14:00', () => {
    // FullCalendar liefert nach dem Ziehen die lokale Wandzeit als Date. Liegt das Ziel
    // nach der Umstellung (26.10., Winterzeit), muss der Offset +01:00 sein, nicht +02:00.
    const r = zuAenderung({ start: new Date(2026, 9, 26, 14, 0), end: new Date(2026, 9, 26, 15, 0) });
    expect(r).toEqual({ beginn: '2026-10-26T14:00:00+01:00', dauer_minuten: 60 });
  });

  it('ohne Ende gilt die Standarddauer', () => {
    expect(zuAenderung({ start: new Date(2026, 9, 20, 10, 0), end: null }, 45).dauer_minuten).toBe(45);
  });

  it('isoMitOffset kennt beide Offsets', () => {
    expect(isoMitOffset(new Date(2026, 9, 25, 1, 30))).toBe('2026-10-25T01:30:00+02:00');
    expect(isoMitOffset(new Date(2026, 9, 25, 4, 5))).toBe('2026-10-25T04:05:00+01:00');
  });
});

describe('braucheBestaetigung', () => {
  it('nur bei kunde', () => {
    expect(braucheBestaetigung('kunde')).toBe(true);
    for (const a of ['eigen', 'handy', 'kollege', '']) expect(braucheBestaetigung(a)).toBe(false);
  });
});
