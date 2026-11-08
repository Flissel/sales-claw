import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ausgeschaltet, farbeFuer, filtern, PALETTE, umschalten, zuruecksetzen } from './ebenen';

const ev = (ebene: string) => ({ extendedProps: { ebene } });

describe('farbeFuer', () => {
  it('feste Palette aus 8 Farben, wiederholt sich danach', () => {
    expect(PALETTE).toHaveLength(8);
    expect(new Set(PALETTE).size).toBe(8);
    expect(farbeFuer('a', 0)).toBe(PALETTE[0]);
    expect(farbeFuer('b', 9)).toBe(PALETTE[1]);
  });
  it('kein Kalender sieht aus wie Eigene Termine, Kundentermine oder Laden-Kalender', () => {
    // Browser-Probe 08.11.: "Felix Gmail" war so blau wie "Eigene Termine".
    for (const fest of ['#2563eb', '#b45309', '#9ca3af', '#c2410c', '#a16207']) {
      expect(PALETTE).not.toContain(fest);
    }
  });
});

describe('filtern', () => {
  it('ausgeschaltete Ebene wird gefiltert', () => {
    const liste = [ev('q1'), ev('q2'), ev('eigen')];
    expect(filtern(liste, new Set(['q1']))).toEqual([ev('q2'), ev('eigen')]);
    expect(filtern(liste, new Set())).toHaveLength(3);
  });
});

function speicher(): Storage {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => { m.set(k, v); },
    removeItem: (k: string) => { m.delete(k); },
    clear: () => m.clear(),
    key: () => null,
    get length() { return m.size; },
  };
}

describe('umschalten', () => {
  beforeEach(() => { zuruecksetzen(); });
  afterEach(() => { vi.unstubAllGlobals(); zuruecksetzen(); });
  it('merkt sich ausgeschaltete Ebenen und schaltet zurueck', () => {
    vi.stubGlobal('localStorage', speicher());
    expect(ausgeschaltet().size).toBe(0);
    umschalten('q1');
    expect([...ausgeschaltet()]).toEqual(['q1']);
    umschalten('q1');
    expect(ausgeschaltet().size).toBe(0);
  });
  it('funktioniert ohne Speicher (Zugriff wirft)', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('gesperrt'); },
      setItem: () => { throw new Error('gesperrt'); },
    });
    expect(ausgeschaltet().size).toBe(0);
    expect(() => umschalten('q1')).not.toThrow();
    expect(ausgeschaltet().has('q1')).toBe(true);
    expect(filtern([ev('q1'), ev('q2')], ausgeschaltet())).toEqual([ev('q2')]);
    umschalten('q1');
    expect(ausgeschaltet().size).toBe(0);
  });
  it('kaputter Inhalt ergibt eine leere Menge', () => {
    const sp = speicher();
    sp.setItem('vk-ebenen-aus', '{kein json');
    vi.stubGlobal('localStorage', sp);
    expect(ausgeschaltet().size).toBe(0);
  });
});
