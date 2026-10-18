import { describe, expect, it } from 'vitest';

import { istLeer, istPlatz } from './bildfeld';

describe('istLeer', () => {
  it('Platzhalter und leere Adresse sind leer', () => {
    expect(istLeer('/medien/datei/platzhalter-2x1.png')).toBe(true);
    expect(istLeer('')).toBe(true);
    expect(istLeer('/medien/datei/nl-1234abcd-kopf.jpg')).toBe(false);
  });
});

describe('Gestaltungsflaeche', () => {
  const flaeche = {
    url: 'medien:gs-aaaaaaaaaaaa.jpg',
    width: 600,
    height: 400,
    gestaltung: { version: 1, format: 'quer', hintergrund: '#FFFFFF', ebenen: [] },
  };
  it('ist kein Bildplatz', () => {
    expect(istPlatz(flaeche)).toBe(false);
  });
  it('ohne gestaltung bleibt es ein Bildplatz', () => {
    expect(istPlatz({ width: 600, height: 400, gestaltung: null })).toBe(true);
  });
});
