import { describe, expect, it } from 'vitest';

import {
  AnhangChip,
  AuswahlChip,
  chipHinzu,
  dateiPruefen,
  KURZ_MAX,
  kontextBauen,
  kurzText,
  MAX_ANHAENGE,
  MAX_AUSWAHL,
  MAX_DATEI,
  sendenErlaubt,
} from './chatKontext';

const block = (id: string, kurz = 'Text · x'): AuswahlChip => ({ art: 'block', id, kurz });
const anhang = (name: string, status: AnhangChip['status'], art: AnhangChip['art'] = 'bild'): AnhangChip => ({
  id: 'k-' + name,
  name,
  art,
  status,
  fortschritt: status === 'fertig' ? 1 : 0.4,
});

describe('chipHinzu', () => {
  it('haengt an und laesst Doppelte weg', () => {
    const a = chipHinzu([], block('h'));
    expect(a).toEqual([block('h')]);
    expect(chipHinzu(a, block('h', 'anders'))).toBe(a);
    // gleiche id, andere Art oder andere Flaeche ist ein anderes Element
    expect(chipHinzu(a, { art: 'ebene', id: 'h', flaeche: 'f', kurz: 'Text-Ebene · h' })).toHaveLength(2);
    const e = chipHinzu([], { art: 'ebene', id: 'e-1', flaeche: 'f1', kurz: 'k' });
    expect(chipHinzu(e, { art: 'ebene', id: 'e-1', flaeche: 'f2', kurz: 'k' })).toHaveLength(2);
  });

  it('hoechstens 8', () => {
    let l: AuswahlChip[] = [];
    for (let i = 0; i < 10; i++) l = chipHinzu(l, block('b' + i));
    expect(l).toHaveLength(MAX_AUSWAHL);
    expect(MAX_AUSWAHL).toBe(8);
    expect(l.map((c) => c.id)).toEqual(['b0', 'b1', 'b2', 'b3', 'b4', 'b5', 'b6', 'b7']);
  });

  it('nimmt keine ids an, die das Pult ablehnt', () => {
    expect(chipHinzu([], block('a b'))).toEqual([]);
    expect(chipHinzu([], block(''))).toEqual([]);
    expect(chipHinzu([], block('x'.repeat(65)))).toEqual([]);
    expect(chipHinzu([], { art: 'ebene', id: 'e-1', flaeche: 'ä', kurz: 'k' })).toEqual([]);
  });

  it('kuerzt zu lange Kurztexte', () => {
    const l = chipHinzu([], block('h', 'y'.repeat(200)));
    expect(l[0].kurz.length).toBeLessThanOrEqual(KURZ_MAX);
  });
});

describe('kurzText', () => {
  it('Bloecke: Art und Anfang des Inhalts', () => {
    expect(kurzText({ type: 'Heading', data: { props: { text: 'Goldener Herbst im Laden – alles neu' } } })).toBe('Überschrift · Goldener Herbst im Laden …');
    expect(kurzText({ type: 'Text', data: { props: { text: 'Hallo **Welt**\nzweite Zeile' } } })).toBe('Text · Hallo Welt');
    expect(kurzText({ type: 'Button', data: { props: { text: 'Jetzt ansehen' } } })).toBe('Knopf · Jetzt ansehen');
    expect(kurzText({ type: 'Image', data: { props: { url: 'medien:held_bild.jpg' } } })).toBe('Bild · held_bild');
    expect(kurzText({ type: 'Image', data: { props: { url: '/medien/datei/held%20bild.png' } } })).toBe('Bild · held bild');
    expect(kurzText({ type: 'Image', data: { props: { url: 'medien:logo.png', alt: 'Kopf', gestaltung: { ebenen: [] } } } })).toBe('Fläche · Kopf');
    expect(kurzText({ type: 'Divider', data: {} })).toBe('Trennlinie');
    expect(kurzText({ type: 'Heading', data: { props: { text: '   ' } } })).toBe('Überschrift');
  });

  it('Ebenen', () => {
    expect(kurzText({ id: 'e-1', art: 'text', text: 'Neu im Oktober\nmehr' } as never)).toBe('Text-Ebene · Neu im Oktober');
    expect(kurzText({ id: 'e-2', art: 'bild', quelle: 'medien:held_bild.png' } as never)).toBe('Bild-Ebene · held_bild');
  });

  it('nie laenger als KURZ_MAX', () => {
    expect(kurzText({ type: 'Text', data: { props: { text: 'w'.repeat(500) } } }).length).toBeLessThanOrEqual(KURZ_MAX);
  });
});

describe('dateiPruefen', () => {
  const datei = (name: string, size = 1000) => ({ name, size });
  it('Bilder und Dokumente', () => {
    for (const n of ['a.jpg', 'a.JPEG', 'a.png', 'a.webp']) expect(dateiPruefen(datei(n))).toEqual({ art: 'bild' });
    for (const n of ['a.pdf', 'a.docx', 'a.txt', 'a.md']) expect(dateiPruefen(datei(n))).toEqual({ art: 'dokument' });
  });
  it('falscher Typ, zu gross, leer', () => {
    expect(dateiPruefen(datei('a.gif'))).toEqual({ grund: expect.stringContaining('Typ') });
    expect(dateiPruefen(datei('ohne'))).toEqual({ grund: expect.stringContaining('Typ') });
    expect(dateiPruefen(datei('a.png', MAX_DATEI + 1))).toEqual({ grund: expect.stringContaining('15 MB') });
    expect(dateiPruefen(datei('a.png', MAX_DATEI))).toEqual({ art: 'bild' });
    expect(dateiPruefen(datei('a.pdf', 0))).toEqual({ grund: expect.stringContaining('leer') });
  });
});

describe('kontextBauen', () => {
  it('nur fertige Anhaenge, Form wie das Pult sie prueft', () => {
    const k = kontextBauen(
      [block('h', 'Überschrift · x'), { art: 'ebene', id: 'e-1', flaeche: 'f', kurz: 'Text-Ebene · y' }],
      [anhang('a.png', 'fertig'), anhang('b.png', 'laedt'), anhang('c.pdf', 'fehler', 'dokument'), anhang('d.pdf', 'fertig', 'dokument')],
    );
    expect(k).toEqual({
      auswahl: [
        { art: 'block', id: 'h', kurz: 'Überschrift · x' },
        { art: 'ebene', id: 'e-1', flaeche: 'f', kurz: 'Text-Ebene · y' },
      ],
      anhaenge: [
        { name: 'a.png', art: 'bild' },
        { name: 'd.pdf', art: 'dokument' },
      ],
    });
  });
  it('hoechstens 5 Anhaenge und 8 Auswahl', () => {
    const viele = Array.from({ length: 7 }, (_, i) => anhang(`b${i}.png`, 'fertig'));
    const auswahl = Array.from({ length: 9 }, (_, i) => block('b' + i));
    const k = kontextBauen(auswahl, viele);
    expect(k.anhaenge).toHaveLength(MAX_ANHAENGE);
    expect(k.auswahl).toHaveLength(MAX_AUSWAHL);
  });
});

describe('sendenErlaubt', () => {
  it('erst wenn kein Upload mehr laeuft', () => {
    expect(sendenErlaubt([])).toBe(true);
    expect(sendenErlaubt([anhang('a.png', 'fertig'), anhang('b.png', 'fehler')])).toBe(true);
    expect(sendenErlaubt([anhang('a.png', 'fertig'), anhang('b.png', 'laedt')])).toBe(false);
  });
});
