import { describe, expect, it } from 'vitest';
import { hoehe, zoomFuer, skalieren, drehen, einrasten, hinweise, verlauf, neueGestaltung, neueId, zuEinheit } from './gestaltung';
import { GestaltungSchema, SCHNITTE } from './schemata';

const text = { id: 't', art: 'text' as const, text: 'Hallo', schrift: 'dm-sans', gewicht: 700, kursiv: false, groesse: 48,
  farbe: '#000000', ausrichtung: 'mitte' as const, zeilenabstand: 1.2, x: 300, y: 200, drehung: 0 };
const bild = { id: 'b', art: 'bild' as const, quelle: 'medien:a.png', x: 100, y: 100, breite: 200, drehung: 0 };

describe('gestaltung', () => {
  it('hoehen', () => expect([hoehe('quer'), hoehe('quadrat'), hoehe('hoch'), hoehe('banner')]).toEqual([400, 600, 750, 200]));
  it('zoom passt in den Platz und ist begrenzt', () => {
    expect(zoomFuer(1200, 2000, 'quer')).toBe(2);
    expect(zoomFuer(600, 300, 'quer')).toBeCloseTo(0.75);
  });
  it('zuEinheit teilt durch zoom', () => expect(zuEinheit(150, 90, 1.5)).toEqual({ x: 100, y: 60 }));
  it('scroll skaliert symmetrisch und begrenzt', () => {
    const groesser = skalieren(bild, -100) as typeof bild;
    expect(groesser.breite).toBeCloseTo(220);
    expect((skalieren(groesser, 100) as typeof bild).breite).toBeCloseTo(200);
    expect((skalieren({ ...text, groesse: 159 }, -1000) as typeof text).groesse).toBe(160);
    expect((skalieren({ ...bild, breite: 9 }, 1000) as typeof bild).breite).toBe(8);
  });
  it('shift-scroll dreht und bricht um', () => {
    expect(drehen(bild, 200).drehung).toBe(10);
    expect(drehen({ ...bild, drehung: 175 }, 200).drehung).toBe(-175);
  });
  it('rastet an der Flaechenmitte ein', () => {
    const r = einrasten({ ...bild, x: 303, y: 197 }, { w: 200, h: 100 }, [], 'quer');
    expect(r).toMatchObject({ x: 300, y: 200 });
    expect(r.linien).toEqual(expect.arrayContaining([{ achse: 'x', wert: 300 }, { achse: 'y', wert: 200 }]));
  });
  it('rastet nicht bei grossem Abstand', () => expect(einrasten({ ...bild, x: 250 }, { w: 10, h: 10 }, [], 'quer').x).toBe(250));
  it('handy-hinweis', () => {
    expect(hinweise({ ...neueGestaltung('#FFFFFF'), ebenen: [{ ...text, groesse: 18 }] })).toEqual(['Text „Hallo“ ist am Handy unter 12 px']);
    expect(hinweise({ ...neueGestaltung('#FFFFFF'), ebenen: [text] })).toEqual([]);
  });
  it('verlauf zurueck und vor', () => {
    const v = verlauf(1); v.setzen(2); v.setzen(3);
    expect(v.zurueck()).toBe(true); expect(v.jetzt()).toBe(2);
    expect(v.vor()).toBe(true); expect(v.jetzt()).toBe(3); expect(v.vor()).toBe(false);
  });
  it('neue id kollidiert nicht', () => {
    const ids = Array.from({ length: 50 }, () => neueId(['e-000000']));
    expect(ids.every((i) => /^e-[0-9a-f]{6}$/.test(i) && i !== 'e-000000')).toBe(true);
  });
  it('schema gleicht python-grenzen', () => {
    const g = { ...neueGestaltung('#FFFFFF'), ebenen: [text, bild] };
    expect(GestaltungSchema.safeParse(g).success).toBe(true);
    expect(GestaltungSchema.safeParse({ ...g, format: 'a4' }).success).toBe(false);
    expect(GestaltungSchema.safeParse({ ...g, ebenen: [{ ...text, text: 'x'.repeat(201) }] }).success).toBe(false);
    expect(GestaltungSchema.safeParse({ ...g, ebenen: Array.from({ length: 21 }, (_, i) => ({ ...bild, id: 'e' + i })) }).success).toBe(false);
    expect(GestaltungSchema.safeParse({ ...g, ebenen: [{ ...text, schrift: 'arial' }] }).success).toBe(false);
  });
  it('schema lehnt nicht vorhandene Schnitte und weitere Grenzverletzungen ab', () => {
    const g = neueGestaltung('#FFFFFF');
    const ok = (e: object) => GestaltungSchema.safeParse({ ...g, ebenen: [e] }).success;
    expect(ok({ ...text, gewicht: 400 })).toBe(true);
    expect(ok({ ...text, gewicht: 500 })).toBe(false);
    expect(ok({ ...text, schrift: 'playfair', gewicht: 900, kursiv: true })).toBe(false);
    expect(ok({ ...text, text: '1\n2\n3\n4\n5\n6\n7' })).toBe(false);
    expect(ok({ ...bild, quelle: 'medien:a..b.png' })).toBe(false);
    expect(ok({ ...bild, quelle: 'medien:a.svg' })).toBe(false);
    expect(ok({ ...text, farbe: '#fff' })).toBe(false);
    expect(ok({ ...text, id: 'a b' })).toBe(false);
  });
  it('schema gleicht dem Server: leerer Text, doppelte ids, Codepunkte', () => {
    const g = neueGestaltung('#FFFFFF');
    const ok = (ebenen: object[]) => GestaltungSchema.safeParse({ ...g, ebenen }).success;
    expect(ok([{ ...text, text: '' }])).toBe(false);
    expect(ok([{ ...text, text: ' \n  ' }])).toBe(false);
    expect(ok([text, { ...bild, id: 't' }])).toBe(false);
    expect(ok([{ ...text, text: '😀'.repeat(200) }])).toBe(true);
    expect(ok([{ ...text, text: '😀'.repeat(201) }])).toBe(false);
  });
  it('hinweis nennt nur die erste Zeile', () => {
    expect(hinweise({ ...neueGestaltung('#FFFFFF'), ebenen: [{ ...text, text: 'Eins\nZwei', groesse: 18 }] }))
      .toEqual(['Text „Eins“ ist am Handy unter 12 px']);
  });
  it('SCHNITTE entspricht dem Register (22 Schnitte)', () => {
    const alle = Object.entries(SCHNITTE).flatMap(([id, l]) => l.map(([g, k]) => `${id}:${g}:${k ? 'i' : 'n'}`)).sort();
    expect(alle).toEqual([
      'cormorant:400:n', 'cormorant:400:i', 'dm-sans:400:n', 'dm-sans:700:n', 'playfair:900:n',
      'poppins:400:n', 'poppins:600:n', 'poppins:700:n', 'young-serif:400:n',
      'manrope:300:n', 'manrope:400:n', 'manrope:700:n', 'bodoni:500:n', 'bodoni:500:i',
      'montserrat:400:n', 'montserrat:600:n', 'josefin:300:n', 'josefin:700:n',
      'oxanium:600:n', 'oxanium:700:n', 'rajdhani:500:n', 'rajdhani:600:n',
    ].sort());
    expect(alle).toHaveLength(22);
  });
});
