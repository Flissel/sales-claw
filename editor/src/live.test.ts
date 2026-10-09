import { describe, expect, it } from 'vitest';

import { anzeigbar, geaenderteBloecke, schrittText, zuletztGeaendert } from './live';

const text = (t: string) => ({ type: 'Text', data: { props: { text: t } } });

const VORHER = {
  root: { type: 'EmailLayout', data: { childrenIds: ['kopf', 'kasten', 'fuss'] } },
  kopf: text('Kopf'),
  kasten: { type: 'Container', data: { props: { childrenIds: ['innen'] } } },
  innen: text('Innen'),
  fuss: text('Fuss'),
};

describe('geaenderteBloecke', () => {
  it('nichts geaendert: leer', () => {
    expect(geaenderteBloecke(VORHER, structuredClone(VORHER))).toEqual([]);
  });

  it('geaenderter Block per Inhalt, nicht per Referenz', () => {
    const nachher = { ...structuredClone(VORHER), innen: text('Neu') };
    expect(geaenderteBloecke(VORHER, nachher)).toEqual(['innen']);
  });

  it('Schluesselreihenfolge zaehlt nicht als Aenderung', () => {
    const nachher = { ...structuredClone(VORHER), kopf: { data: { props: { text: 'Kopf' } }, type: 'Text' } };
    expect(geaenderteBloecke(VORHER, nachher)).toEqual([]);
  });

  it('neue Bloecke zaehlen, geloeschte nicht; Reihenfolge wie im Dokument', () => {
    const nachher = {
      root: { type: 'EmailLayout', data: { childrenIds: ['neu', 'kopf', 'kasten'] } },
      neu: text('Neu'),
      kopf: text('Kopf geaendert'),
      kasten: VORHER.kasten,
      innen: VORHER.innen,
    };
    // fuss geloescht -> fehlt; root geaendert (Kinder), neu und kopf in Dokumentreihenfolge
    expect(geaenderteBloecke(VORHER, nachher)).toEqual(['root', 'neu', 'kopf']);
  });

  it('unerreichbare Bloecke zaehlen nicht', () => {
    const nachher = { ...structuredClone(VORHER), waise: text('weg') };
    expect(geaenderteBloecke(VORHER, nachher)).toEqual([]);
  });
});

describe('zuletztGeaendert', () => {
  it('letzter geaenderter Block in Dokumentreihenfolge, ohne root', () => {
    const nachher = { ...structuredClone(VORHER), kopf: text('a'), fuss: text('b') };
    expect(zuletztGeaendert(VORHER, nachher)).toBe('fuss');
  });

  it('ein Behaelter, der nur ein geaendertes Kind hat, tritt hinter das Kind zurueck', () => {
    const nachher = structuredClone(VORHER);
    nachher.kasten = { type: 'Container', data: { props: { childrenIds: ['innen', 'zwei'] } } };
    (nachher as Record<string, unknown>).zwei = text('Zwei');
    expect(zuletztGeaendert(VORHER, nachher)).toBe('zwei');
  });

  it('nur root geaendert oder nichts: null', () => {
    const nachher = { ...structuredClone(VORHER), root: { type: 'EmailLayout', data: { childrenIds: ['kopf', 'kasten', 'fuss'], backdropColor: '#000000' } } };
    expect(zuletztGeaendert(VORHER, nachher)).toBeNull();
    expect(zuletztGeaendert(VORHER, VORHER)).toBeNull();
  });
});

describe('schrittText', () => {
  it('Schritt N · Text', () => {
    expect(schrittText({ schritt: 'Titel links oben setzen', schritt_nr: 3, zwischenstand: null, stopp: null, denken: '', schritte: [] })).toBe(
      'Schritt 3 · Titel links oben setzen',
    );
  });

  it('ohne Text nur die Nummer, vor dem ersten Schritt null', () => {
    expect(schrittText({ schritt: '  ', schritt_nr: 2, zwischenstand: null, stopp: null, denken: '', schritte: [] })).toBe('Schritt 2');
    expect(schrittText({ schritt: '', schritt_nr: 0, zwischenstand: null, stopp: null, denken: '', schritte: [] })).toBeNull();
    expect(schrittText(null)).toBeNull();
  });
});

describe('anzeigbar', () => {
  it('ein vollstaendiges Dokument ist anzeigbar', () => {
    expect(anzeigbar(VORHER)).toBe(true);
  });

  it('fehlendes Kind, unbekannter Typ oder kein root: nicht anzeigbar (der Canvas wuerde abstuerzen)', () => {
    expect(anzeigbar({ ...VORHER, kasten: { type: 'Container', data: { props: { childrenIds: ['fehlt'] } } } })).toBe(false);
    expect(anzeigbar({ ...VORHER, kopf: { type: 'Html', data: {} } })).toBe(false);
    expect(anzeigbar({ kopf: text('x') })).toBe(false);
    expect(anzeigbar({ ...VORHER, kopf: { type: 'Text' } })).toBe(false);
  });
});
