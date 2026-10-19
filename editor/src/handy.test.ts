import { describe, expect, it } from 'vitest';

import { HANDY_GRENZE, vorschauAdresse } from './handy';

describe('vorschauAdresse', () => {
  it('haengt Fassung und Format an', () => {
    expect(vorschauAdresse('/marketing/entwurf/a/vorschau', 3)).toBe('/marketing/entwurf/a/vorschau?fassung=3&format=handy');
  });
  it('nimmt & wenn die Adresse schon eine Abfrage hat', () => {
    expect(vorschauAdresse('/x?y=1', 2)).toBe('/x?y=1&fassung=2&format=handy');
  });
});

describe('HANDY_GRENZE', () => {
  it('trifft alles unter 768 px', () => {
    expect(HANDY_GRENZE).toBe('(max-width:767.98px)');
  });
});
