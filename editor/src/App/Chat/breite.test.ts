import { afterEach, describe, expect, it, vi } from 'vitest';

import { BREITE_MIN, BREITE_SCHLUESSEL, BREITE_START, breiteBegrenzen, breiteLesen, breiteSchreiben } from './breite';

function speicher(werte: Record<string, string> = {}) {
  const m = new Map(Object.entries(werte));
  vi.stubGlobal('localStorage', { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) });
  return m;
}

afterEach(() => vi.unstubAllGlobals());

describe('Breite der Chat-Leiste', () => {
  it('startet mit 440 px ohne gemerkte Breite', () => {
    speicher();
    expect(breiteLesen(1600)).toBe(BREITE_START);
    expect(BREITE_START).toBe(440);
  });
  it('nimmt die gemerkte Breite, begrenzt auf 360 px bis zur halben Fensterbreite', () => {
    speicher({ [BREITE_SCHLUESSEL]: '600' });
    expect(breiteLesen(1600)).toBe(600);
    expect(breiteLesen(1000)).toBe(500);
    expect(breiteBegrenzen(200, 1600)).toBe(BREITE_MIN);
    expect(breiteBegrenzen(Number.NaN, 1600)).toBe(440);
    expect(breiteBegrenzen(500, 600)).toBe(BREITE_MIN);   // schmales Fenster: nie unter 360
  });
  it('kaputter Wert: Vorgabe', () => {
    speicher({ [BREITE_SCHLUESSEL]: 'breit' });
    expect(breiteLesen(1600)).toBe(440);
  });
  it('ohne Speicher (Zugriff wirft): Vorgabe, Schreiben wirft nicht', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('gesperrt'); },
      setItem: () => { throw new Error('gesperrt'); },
    });
    expect(breiteLesen(1600)).toBe(440);
    expect(() => breiteSchreiben(500)).not.toThrow();
  });
  it('schreibt gerundet unter dem Schluessel', () => {
    const m = speicher();
    breiteSchreiben(512.6);
    expect(m.get('vibemind.editor.chatbreite')).toBe('513');
  });
});
