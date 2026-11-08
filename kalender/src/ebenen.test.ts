import { afterEach, describe, expect, it, vi } from 'vitest';

import { ausgeschaltet, farbeFuer, filtern, PALETTE, umschalten } from './ebenen';

const ev = (ebene: string) => ({ extendedProps: { ebene } });

describe('farbeFuer', () => {
  it('feste Palette aus 8 Farben, wiederholt sich danach', () => {
    expect(PALETTE).toHaveLength(8);
    expect(new Set(PALETTE).size).toBe(8);
    expect(farbeFuer('a', 0)).toBe(PALETTE[0]);
    expect(farbeFuer('b', 9)).toBe(PALETTE[1]);
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
  afterEach(() => { vi.unstubAllGlobals(); });
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
  });
  it('kaputter Inhalt ergibt eine leere Menge', () => {
    const sp = speicher();
    sp.setItem('vk-ebenen-aus', '{kein json');
    vi.stubGlobal('localStorage', sp);
    expect(ausgeschaltet().size).toBe(0);
  });
});
