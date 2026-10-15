import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { EbenenInhalt } from './App/Gestaltung/Flaeche';
import { ebenenName, neueFormEbene } from './App/Gestaltung/hilfen';
import EmailLayoutPropsSchema from './documents/blocks/EmailLayout/EmailLayoutPropsSchema';
import { Ebene, Gestaltung, neueGestaltung, skalieren } from './gestaltung';
import { GestaltungSchema, SCHRIFT_IDS, VORLAGEN_SCHRIFT_IDS } from './schemata';

// Paket 3 (Marketing gestaltung.py): gleiche Felder und Grenzen wie der Rechner.
const form = { id: 'f', art: 'form', form: 'kreis', x: 480, y: 90, breite: 120, hoehe: 120, farbe: '#C8553D', drehung: 0 };
const bild = { id: 'b', art: 'bild', quelle: 'medien:a.jpg', x: 1, y: 2, breite: 50, drehung: 0 };
const text = { id: 't', art: 'text', text: 'Neu!', schrift: 'caveat', gewicht: 700, kursiv: false, groesse: 48,
  farbe: '#FFFFFF', ausrichtung: 'mitte', zeilenabstand: 1.2, x: 300, y: 200, drehung: 0 };
const g = (ebenen: unknown[]) => ({ version: 1, format: 'quer', hintergrund: '#FFFFFF', ebenen });

describe('Freiere Flaeche: Schema', () => {
  it('nimmt Form, Handschrift, Texthintergrund, Rahmen/Kreis/Schatten und Deckkraft', () => {
    const r = GestaltungSchema.safeParse(g([
      { ...form, deckkraft: 80 },
      { ...form, id: 'r', form: 'rechteck', rundung: 24 },
      { ...bild, rahmen: 12, rundung: 8, kreis: true, schatten: true },
      { ...text, hintergrund: '#C8553D' },
    ]));
    expect(r.success).toBe(true);
  });
  it('lehnt falsche Werte ab wie der Rechner', () => {
    for (const falsch of [
      { ...form, form: 'stern' }, { ...form, hoehe: 4 }, { ...form, deckkraft: 120 },
      { ...bild, rahmen: 81 }, { ...bild, rundung: 301 }, { ...bild, kreis: 'ja' },
      { ...text, hintergrund: 'blau' }, { ...text, gewicht: 500 },
    ]) {
      expect(GestaltungSchema.safeParse(g([falsch])).success, JSON.stringify(falsch)).toBe(false);
    }
  });
  it('Handschrift nur fuer Ebenen, nicht als Schriftpaar der Vorlage (DB-Liste)', () => {
    expect(SCHRIFT_IDS).toContain('caveat');
    expect(VORLAGEN_SCHRIFT_IDS).not.toContain('caveat');
    expect(EmailLayoutPropsSchema.safeParse({ childrenIds: [], schriften: { anzeige: 'caveat', text: 'dm-sans' } }).success)
      .toBe(false);
  });
});

describe('Freiere Flaeche: Darstellung und Bedienung', () => {
  const zeig = (e: unknown) => renderToStaticMarkup(React.createElement(EbenenInhalt, { e: e as Ebene }));
  it('Form: Kreis und abgerundetes Rechteck mit Deckkraft', () => {
    const k = zeig({ ...form, deckkraft: 50 });
    expect(k).toContain('width:120px');
    expect(k).toContain('border-radius:50%');
    expect(k).toContain('opacity:0.5');
    expect(zeig({ ...form, form: 'rechteck', rundung: 24 })).toContain('border-radius:24px');
  });
  it('Text: Band hinter dem Text', () => {
    expect(zeig({ ...text, hintergrund: '#C8553D' })).toContain('background-color:#C8553D');
  });
  it('Bild: Rahmen, Kreis, Schatten', () => {
    const h = zeig({ ...bild, rahmen: 12, kreis: true, schatten: true });
    expect(h).toContain('padding:12px');
    expect(h).toContain('border-radius:50%');
    expect(h).toContain('drop-shadow');
  });
  it('Form skaliert mit dem Scrollrad in Breite und Hoehe', () => {
    const s = skalieren(form as Ebene, -100) as typeof form;
    expect(s.breite).toBeCloseTo(132);
    expect(s.hoehe).toBeCloseTo(132);
  });
  it('neue Form-Ebene in der Ladenfarbe, mit Namen in der Liste', () => {
    const gs: Gestaltung = neueGestaltung('#FAF7F2');
    const e = neueFormEbene('e-1', gs, { data: { textColor: '#2b2724', rollen: {} } });
    expect(GestaltungSchema.safeParse({ ...gs, ebenen: [e] }).success).toBe(true);
    expect(ebenenName(e)).toBe('Kreis');
  });
});
