import { describe, expect, it } from 'vitest';
import { ebenenStil, familieFuer, neueEbene, speicherGrund, type Seite, type TextEbeneS } from './seite';

function leer(): Seite {
  return {
    version: 1, breite: 600, hoehe: 1200,
    hintergrund: { farbe: '#ffffff', bild: null },
    schriften: { anzeige: 'montserrat', text: 'dm-sans' },
    ebenen: [
      { id: 'titel', art: 'text', x: 300, y: 120, breite: 520, hoehe: 120, text: 'Überschrift', rolle: 'ANZEIGE', groesse: 48, farbe: '#111111', ausrichtung: 'mitte' },
      { id: 'text', art: 'text', x: 300, y: 300, breite: 480, hoehe: 120, text: 'Hier steht Ihr Text.', rolle: 'TEXT', groesse: 17, farbe: '#333333' },
      { id: 'knopf', art: 'knopf', x: 300, y: 460, breite: 220, hoehe: 48, text: 'Mehr erfahren', link: 'https://example.com', farbe: '#5b3fd6', textfarbe: '#ffffff' },
    ],
  };
}
const text = (t: Partial<TextEbeneS>): TextEbeneS => ({ id: 'a', art: 'text', x: 0, y: 0, breite: 10, hoehe: 10, text: 'x', rolle: 'TEXT', groesse: 17, farbe: '#000000', ...t });

describe('familieFuer', () => {
  it('TEXT ist nur der Mail-Stapel', () => {
    const s = leer();
    s.schriften.text = 'dm-sans';
    const f = familieFuer('TEXT', s);
    expect(f).toBe('Arial, Helvetica, sans-serif');
    expect(f).not.toContain('DM Sans');
  });
  it('ANZEIGE: Webschrift vor dem Stapel', () => {
    const f = familieFuer('ANZEIGE', leer());
    expect(f.startsWith('Montserrat')).toBe(true);
    expect(f.endsWith('Arial, Helvetica, sans-serif')).toBe(true);
  });
  it('HAND ist Caveat', () => expect(familieFuer('HAND', leer()).startsWith('Caveat')).toBe(true));
  it('unbekannte ID faellt auf dm-sans zurueck', () => {
    const s = leer();
    s.schriften.text = 'weg';
    s.schriften.anzeige = 'weg';
    expect(familieFuer('TEXT', s)).toBe('Arial, Helvetica, sans-serif');
    expect(familieFuer('ANZEIGE', s)).toContain('DM Sans');
  });
});

describe('ebenenStil', () => {
  it('Mittelpunkt wird zu left/top', () => {
    const st = ebenenStil({ id: 'f', art: 'form', form: 'rechteck', farbe: '#000000', x: 300, y: 200, breite: 100, hoehe: 50, drehung: 12 });
    expect(st).toMatchObject({ left: 250, top: 175, width: 100, height: 50, transform: 'rotate(12deg)' });
  });
  it('Text bekommt minHeight', () => {
    const st = ebenenStil(text({ x: 300, y: 200, breite: 100, hoehe: 50 }));
    expect(st.minHeight).toBe(50);
    expect(st.height).toBeUndefined();
  });
});

describe('speicherGrund', () => {
  it('gueltige Seite', () => expect(speicherGrund(leer())).toBeNull());
  it('81 Ebenen', () => {
    const s = leer();
    s.ebenen = Array.from({ length: 81 }, (_, i) => text({ id: `e${i}` }));
    expect(speicherGrund(s)).toContain('80');
  });
  it('Anrede in ANZEIGE', () => {
    const s = leer();
    s.ebenen = [text({ text: 'Hallo {vorname}', rolle: 'ANZEIGE' })];
    expect(speicherGrund(s)).toContain('Anrede');
  });
  it('Link bei Drehung', () => {
    const s = leer();
    s.ebenen = [text({ text: '[x](https://a.de)', drehung: 5 })];
    expect(speicherGrund(s)).toContain('Links im Text gehen nur in Fließtext');
  });
  it('Bild ohne gueltige Quelle', () => {
    const s = leer();
    s.ebenen = [neueEbene('bild', s)];
    expect(speicherGrund(s)).toContain('nur Bilder aus der Mediathek (medien:…) erlaubt');
    s.ebenen = [neueEbene('bild', s, 'medien:a.png')];
    expect(speicherGrund(s)).toBeNull();
  });
  it('Link nur https', () => {
    const s = leer();
    s.ebenen = [text({ text: '[x](http://a.de)' })];
    expect(speicherGrund(s)).toContain('https');
  });
});

describe('neueEbene', () => {
  it('Mitte und frische ID', () => {
    const s = leer();
    const e = neueEbene('text', s);
    expect(s.ebenen.some((o) => o.id === e.id)).toBe(false);
    expect(e.x).toBe(300);
    expect(e.y).toBe(s.hoehe / 2);
    expect(e).toMatchObject({ text: 'Neuer Text', rolle: 'TEXT', groesse: 17 });
    expect(neueEbene('knopf', s)).toMatchObject({ text: 'Mehr erfahren', link: 'https://example.com' });
  });
});
