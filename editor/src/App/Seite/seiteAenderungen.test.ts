import { describe, expect, it } from 'vitest';

import type { FormEbeneS, Seite } from '../../seite';
import { ebeneDazu, ebeneGeaendert, ebeneVerschoben, ebeneWeg } from './seiteAenderungen';

const f = (id: string): FormEbeneS => ({
  id, art: 'form', form: 'rechteck', farbe: '#000000', x: 300, y: 200, breite: 100, hoehe: 50, drehung: 0,
});
const s: Seite = {
  version: 1, breite: 600, hoehe: 800, hintergrund: { farbe: '#ffffff', bild: null },
  schriften: { anzeige: 'dm-sans', text: 'dm-sans' }, ebenen: [f('a'), f('b'), f('c')],
};

describe('seiteAenderungen', () => {
  it('klemmt geaenderte Ebenen und laesst die id', () => {
    const n = ebeneGeaendert(s, 'a', { x: 9999, id: 'z' });
    expect(n.ebenen[0].x).toBe(1200);
    expect(n.ebenen[0].id).toBe('a');
    expect(ebeneGeaendert(s, 'fehlt', { x: 1 })).toBe(s);
  });
  it('verschiebt die Reihenfolge und stoppt an den Enden', () => {
    expect(ebeneVerschoben(s, 'a', 1).ebenen.map((e) => e.id)).toEqual(['b', 'a', 'c']);
    expect(ebeneVerschoben(s, 'a', -1)).toBe(s);
    expect(ebeneVerschoben(s, 'c', 1)).toBe(s);
  });
  it('fuegt hinzu und loescht', () => {
    expect(ebeneDazu(s, f('d')).ebenen).toHaveLength(4);
    expect(ebeneWeg(s, 'b').ebenen.map((e) => e.id)).toEqual(['a', 'c']);
  });
});
