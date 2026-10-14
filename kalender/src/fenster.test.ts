import { describe, expect, it, vi } from 'vitest';

import { koerperAendern, koerperAnlegen, mitSperre, pruefen, type Werte } from './fenster';

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
