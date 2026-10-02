import { describe, expect, it } from 'vitest';

import { freistellbar, istPlatz } from './bildfeld';

describe('freistellbar', () => {
  it('nur echtes Bild', () => {
    expect(freistellbar({ url: '/medien/datei/nl-1234abcd-kopf.jpg' })).toBe(true);
    expect(freistellbar({ url: '/medien/datei/platzhalter-2x1.png' })).toBe(false);
    expect(freistellbar({ url: '' })).toBe(false);
    expect(freistellbar({ url: '/medien/datei/tech-signal-aaaaaa.png', grafik: true })).toBe(false);
  });
});

describe('Gestaltungsflaeche', () => {
  const flaeche = {
    url: 'medien:gs-aaaaaaaaaaaa.jpg',
    width: 600,
    height: 400,
    gestaltung: { version: 1, format: 'quer', hintergrund: '#FFFFFF', ebenen: [] },
  };
  it('ist weder freistellbar noch Bildplatz', () => {
    expect(freistellbar(flaeche)).toBe(false);
    expect(istPlatz(flaeche)).toBe(false);
  });
  it('ohne gestaltung bleibt es ein Bildplatz', () => {
    expect(istPlatz({ width: 600, height: 400, gestaltung: null })).toBe(true);
    expect(freistellbar({ url: 'medien:nl-1234abcd-kopf.jpg', gestaltung: null })).toBe(true);
  });
});
