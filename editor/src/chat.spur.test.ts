import { describe, expect, it } from 'vitest';

import { denkAusschnitt, schritteLesen } from './chat';
import { gedankenSichtbarLesen, gedankenSichtbarSchreiben } from './App/Chat/Gedanken';

describe('schritteLesen', () => {
  it('nimmt nur {zeit, text} mit Strings, hoechstens 60', () => {
    const roh = [{ zeit: '08:00:01', text: 'a' }, { zeit: 1, text: 'b' }, 'x', { zeit: '08:00:02' },
      ...Array.from({ length: 70 }, (_, i) => ({ zeit: '08:00:03', text: `s${i}` }))];
    const s = schritteLesen(roh);
    expect(s.length).toBe(60);
    expect(s[0]).toEqual({ zeit: '08:00:01', text: 'a' });
  });
  it('liefert [] fuer Nicht-Listen', () => {
    expect(schritteLesen(null)).toEqual([]);
    expect(schritteLesen({})).toEqual([]);
  });
});

describe('denkAusschnitt', () => {
  it('kurz bleibt unveraendert', () => expect(denkAusschnitt('abc')).toBe('abc'));
  it('lang: Ende mit Auslassung', () => {
    const t = denkAusschnitt('A'.repeat(1000) + 'ENDE', 600);
    expect(t.startsWith('…')).toBe(true);
    expect(t.endsWith('ENDE')).toBe(true);
    expect(t.length).toBe(601);
  });
});

describe('gedankenSichtbar', () => {
  it('Vorgabe sichtbar, ueberlebt fehlenden localStorage', () => {
    const alt = globalThis.localStorage;
    // @ts-expect-error - Test ohne localStorage
    delete globalThis.localStorage;
    expect(gedankenSichtbarLesen()).toBe(true);
    expect(() => gedankenSichtbarSchreiben(false)).not.toThrow();
    if (alt) globalThis.localStorage = alt;
  });
});
