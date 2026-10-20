import { describe, expect, it } from 'vitest';

import type { FormEbeneS, Seite, SeitenEbene } from './seite';
import { drehenZu, einrastenSeite, griffZiehen, hoeheZiehen, klemmen } from './seiteGeometrie';

const form = (t: Partial<FormEbeneS> = {}): FormEbeneS => ({
  id: 'a', art: 'form', form: 'rechteck', farbe: '#000000', x: 300, y: 200, breite: 100, hoehe: 50, drehung: 0, ...t,
});

describe('klemmen', () => {
  it('begrenzt Lage, Groesse und normalisiert die Drehung', () => {
    const k = klemmen(form({ x: 5000, breite: 0, drehung: 190 }));
    expect(k.x).toBe(1200);
    expect(k.breite).toBe(1);
    expect(k.drehung).toBe(-170);
  });
});

describe('einrastenSeite', () => {
  it('rastet die Mitte auf die Seitenmitte und meldet die Linie', () => {
    const r = einrastenSeite(form({ x: 297, y: 123 }), [], 1000);
    expect(r.x).toBe(300);
    expect(r.linien).toContainEqual({ art: 'senkrecht', wert: 300 });
  });
  it('rastet die linke Kante auf den Seitenrand', () => {
    const r = einrastenSeite(form({ x: 53, breite: 100 }), [], 1000);
    expect(r.x).toBe(50);
    expect(r.linien).toContainEqual({ art: 'senkrecht', wert: 0 });
  });
  it('rastet an anderen Ebenen', () => {
    const r = einrastenSeite(form({ x: 100, y: 118 }), [form({ id: 'b', x: 400, y: 120, hoehe: 20 })], 1000);
    expect(r.y).toBe(120);
  });
});

describe('griffZiehen', () => {
  it('so: gegenueberliegende Ecke bleibt stehen', () => {
    const e = griffZiehen(form({ x: 300, y: 200 }), 'so', 20, 10, false);
    expect([e.breite, e.hoehe, e.x, e.y]).toEqual([120, 60, 310, 205]);
  });
  it('festes Verhaeltnis bleibt 2:1', () => {
    const e = griffZiehen(form(), 'so', 20, 3, true);
    expect(e.breite / e.hoehe).toBeCloseTo(2);
  });
  it('festes Verhaeltnis an der Grenze: Verhaeltnis und feste Ecke bleiben', () => {
    const e = griffZiehen(form({ breite: 100, hoehe: 1000, x: 300, y: 200 }), 'so', 1000, 10000, true);
    expect(e.hoehe).toBe(6000);
    expect(e.breite).toBeCloseTo(600);
    expect(e.x - e.breite / 2).toBeCloseTo(250);
    expect(e.y - e.hoehe / 2).toBeCloseTo(-300);
  });
  it('90 Grad gedreht: gegenueberliegende Ecke bleibt in Seitenkoordinaten stehen', () => {
    const ecke = (e: SeitenEbene, sx: number, sy: number) => {
      const r = ((e.drehung ?? 0) * Math.PI) / 180;
      const lx = (sx * e.breite) / 2;
      const ly = (sy * e.hoehe) / 2;
      return { x: e.x + lx * Math.cos(r) - ly * Math.sin(r), y: e.y + lx * Math.sin(r) + ly * Math.cos(r) };
    };
    const alt = form({ drehung: 90 });
    const vorher = ecke(alt, -1, -1);
    // Seiten-dx=0, dy=20 ist im Ebenenrahmen (um -90 gedreht) dx=+20.
    const neu = griffZiehen(alt, 'so', 0, 20, false);
    expect(neu.breite).toBe(120);
    expect(neu.hoehe).toBe(50);
    const nachher = ecke(neu, -1, -1);
    expect(nachher.x).toBeCloseTo(vorher.x);
    expect(nachher.y).toBeCloseTo(vorher.y);
  });
});

describe('drehenZu', () => {
  it('Maus rechts vom Mittelpunkt = 0', () => {
    expect(drehenZu(form(), 500, 200, false).drehung).toBeCloseTo(0);
  });
  it('rastet auf 15 Grad', () => {
    const w = (44 * Math.PI) / 180;
    expect(drehenZu(form(), 300 + 100 * Math.cos(w), 200 + 100 * Math.sin(w), true).drehung).toBe(45);
  });
});

describe('hoeheZiehen', () => {
  const s: Seite = {
    version: 1, breite: 600, hoehe: 800, hintergrund: { farbe: '#ffffff', bild: null },
    schriften: { anzeige: 'dm-sans', text: 'dm-sans' }, ebenen: [form()],
  };
  it('klemmt und rundet', () => {
    expect(hoeheZiehen(s, 100).hoehe).toBe(400);
    expect(hoeheZiehen(s, 9000).hoehe).toBe(6000);
    expect(hoeheZiehen(s, 812.6).hoehe).toBe(813);
    expect(hoeheZiehen(s, 500).ebenen).toBe(s.ebenen);
  });
});
