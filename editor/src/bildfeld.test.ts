import { describe, expect, it } from 'vitest';

import { freistellbar } from './bildfeld';

describe('freistellbar', () => {
  it('nur echtes Bild', () => {
    expect(freistellbar({ url: '/medien/datei/nl-1234abcd-kopf.jpg' })).toBe(true);
    expect(freistellbar({ url: '/medien/datei/platzhalter-2x1.png' })).toBe(false);
    expect(freistellbar({ url: '' })).toBe(false);
    expect(freistellbar({ url: '/medien/datei/tech-signal-aaaaaa.png', grafik: true })).toBe(false);
  });
});
