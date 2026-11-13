import { describe, expect, it, vi } from 'vitest';

import { aktenLink, zeigtAktenLink, koerperAendern, koerperAnlegen, mitSperre, pruefen, startWerte, type Werte } from './fenster';

const basis: Werte = {
  art: 'eigen', titel: 'Steuerberater', datum: '2026-10-26', zeit: '14:00', dauer: 60,
  ort: '', notiz: '', lead_id: '', einladung: false,
};

describe('mitSperre (Absenden nur einmal)', () => {
  it('zweimal absenden() -> genau ein API-Aufruf, Knopf waehrenddessen gesperrt', async () => {
    let fertig: (v: string) => void = () => {};
    const api = vi.fn(() => new Promise<string>((r) => { fertig = r; }));
    const knopf = { disabled: false };
    const absenden = mitSperre(knopf, api);
    const a = absenden();
    const b = absenden();
    expect(api).toHaveBeenCalledTimes(1);
    expect(knopf.disabled).toBe(true);
    fertig('ok');
    expect(await a).toBe('ok');
    expect(await b).toBeUndefined();
    expect(knopf.disabled).toBe(false);
    void absenden();
    expect(api).toHaveBeenCalledTimes(2);
  });

  it('gibt den Knopf auch nach einem Fehler wieder frei', async () => {
    const knopf = { disabled: false };
    const absenden = mitSperre(knopf, () => Promise.reject(new Error('weg')));
    await expect(absenden()).rejects.toThrow('weg');
    expect(knopf.disabled).toBe(false);
  });
});

describe('pruefen', () => {
  it('Dauer eigen 5-1440, Kunde 15-480', () => {
    expect(pruefen({ ...basis, dauer: 4 })).toMatch(/5–1440/);
    expect(pruefen({ ...basis, dauer: 1440 })).toBeNull();
    expect(pruefen({ ...basis, art: 'kunde', lead_id: 'x', dauer: 10 })).toMatch(/15–480/);
    expect(pruefen({ ...basis, art: 'kunde', lead_id: 'x', dauer: 481 })).toMatch(/15–480/);
  });
  it('Titel und Kontakt sind Pflicht', () => {
    expect(pruefen({ ...basis, titel: ' ' })).not.toBeNull();
    expect(pruefen({ ...basis, art: 'kunde', lead_id: '' })).toMatch(/Kontakt/);
  });
  it('Datum und Zeit sind Pflicht', () => {
    expect(pruefen({ ...basis, zeit: '' })).not.toBeNull();
  });
});

describe('koerperAnlegen', () => {
  it('eigen: Titel, Beginn mit Offset, Notiz', () => {
    expect(koerperAnlegen({ ...basis, notiz: 'n', ort: 'Praxis' })).toEqual({
      art: 'eigen', titel: 'Steuerberater', beginn: '2026-10-26T14:00:00+01:00', dauer_minuten: 60, ort: 'Praxis', notiz: 'n',
    });
  });
  it('kunde: Thema, lead_id, Einladung, keine Notiz', () => {
    expect(koerperAnlegen({ ...basis, art: 'kunde', lead_id: 'L', notiz: 'weg', einladung: true })).toEqual({
      art: 'kunde', lead_id: 'L', thema: 'Steuerberater', beginn: '2026-10-26T14:00:00+01:00',
      dauer_minuten: 60, ort: '', einladung: true,
    });
  });
});

describe('koerperAendern', () => {
  const altEigen = {
    art: 'eigen' as const, titel: 'Steuerberater', beginn: '2026-10-26T14:00:00+01:00', dauer: 60,
    ort: 'A', notiz: 'n', geaendert_am: 'S',
  };
  it('eigen: alles mit Stempel, Ort darf leer werden', () => {
    expect(koerperAendern({ ...basis, ort: '', notiz: 'n' }, altEigen)).toEqual({
      titel: 'Steuerberater', beginn: '2026-10-26T14:00:00+01:00', dauer_minuten: 60, ort: '', notiz: 'n', geaendert_am: 'S',
    });
  });
  const altKunde = { art: 'kunde' as const, titel: 'Erstgespräch', beginn: '2026-10-26T14:00:00+01:00', dauer: 60, ort: 'Büro' };
  it('kunde: nur Geaendertes, nie Notiz, leerer Ort bleibt unveraendert', () => {
    const w: Werte = { ...basis, art: 'kunde', lead_id: 'L', titel: 'Erstgespräch', ort: '', notiz: 'x', dauer: 90 };
    expect(koerperAendern(w, altKunde)).toEqual({ dauer_minuten: 90 });
  });
  it('kunde ohne Aenderung -> null', () => {
    const w: Werte = { ...basis, art: 'kunde', lead_id: 'L', titel: 'Erstgespräch', ort: 'Büro' };
    expect(koerperAendern(w, altKunde)).toBeNull();
  });
  it('kunde: neue Zeit und neuer Ort', () => {
    const w: Werte = { ...basis, art: 'kunde', lead_id: 'L', titel: 'Erstgespräch', zeit: '15:30', ort: 'Video' };
    expect(koerperAendern(w, altKunde)).toEqual({ beginn: '2026-10-26T15:30:00+01:00', ort: 'Video' });
  });
});

describe('startWerte (Vorgabe aus dem Link)', () => {
  it('kunde waehlt Kundentermin und den Kontakt vor', () => {
    const w = startWerte({ art: 'kunde', kunde: { lead_id: 'abc', name: 'Anna Vorbelegt' } }, {});
    expect(w).toEqual({ art: 'kunde', leadId: 'abc', gewaehlt: 'Anna Vorbelegt' });
  });
  it('ohne Vorgabe bleibt es ein eigener Termin ohne Kontakt', () => {
    expect(startWerte({}, {})).toEqual({ art: 'eigen', leadId: '', gewaehlt: '' });
  });
  it('beim Bearbeiten gilt weiter die Art des Termins', () => {
    expect(startWerte({ modus: 'bearbeiten' }, { art: 'kunde', lead_id: 'x' }).art).toBe('kunde');
  });
});

describe('aktenLink', () => {
  it('kodiert # und @ der Kalender-UID', () => {
    expect(aktenLink('abc@google.com#2026-11-12T09:00:00+00:00'))
      .toBe('/termine/abc%40google.com%232026-11-12T09%3A00%3A00%2B00%3A00');
  });
  it('einfache UID bleibt lesbar', () => {
    expect(aktenLink('u1')).toBe('/termine/u1');
  });
});

describe('zeigtAktenLink', () => {
  it('Kundentermin mit uid zeigt die Termin-Seite', () => {
    expect(zeigtAktenLink('kunde:1', 'u1', 'voll')).toBe(true);
    expect(zeigtAktenLink('kalender:1', 'u1', 'lesen')).toBe(true);
  });
  it('Rolle kalender sieht keinen Link auf die Termin-Seite (wie Zum Kontakt)', () => {
    expect(zeigtAktenLink('kunde:1', 'u1', 'kalender')).toBe(false);
    expect(zeigtAktenLink('kalender:1', 'u1', 'kalender')).toBe(false);
  });
  it('ohne uid oder ohne Akte kein Link', () => {
    expect(zeigtAktenLink('kunde:1', '', 'voll')).toBe(false);
    expect(zeigtAktenLink('handy:1', 'u1', 'voll')).toBe(false);
  });
});
