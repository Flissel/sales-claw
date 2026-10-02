import { describe, expect, it } from 'vitest';

import { neueGestaltung } from '../../gestaltung';
import { GestaltungSchema } from '../../schemata';

import {
  ebenenName,
  flaecheLesen,
  flaechenHintergrund,
  formatWechseln,
  ladenfarben,
  medienFuerEbenen,
  neueBildEbene,
  neueTextEbene,
  pruefGrund,
  quelleAnzeige,
} from './hilfen';

const root = {
  type: 'EmailLayout',
  data: { canvasColor: '#fafaf7', textColor: '#222222', backdropColor: '#EEEEEE', schriften: { anzeige: 'bodoni' }, rollen: { akzent: '#C0392B', kaputt: 'rot' } },
};

describe('Gestaltungsfenster-Hilfen', () => {
  it('neue Flaeche nimmt die Layout-Flaeche, sonst Weiss', () => {
    expect(flaechenHintergrund(root)).toBe('#FAFAF7');
    expect(flaechenHintergrund({ data: { canvasColor: 'weiss' } })).toBe('#FFFFFF');
    expect(flaechenHintergrund(undefined)).toBe('#FFFFFF');
  });

  it('+ Text: Anzeigeschrift, erster Schnitt, 48, Textfarbe, Mitte - und gueltig', () => {
    const g = { ...neueGestaltung('#FFFFFF'), format: 'hoch' as const };
    const t = neueTextEbene('e-1', g, root);
    expect(t).toMatchObject({ schrift: 'bodoni', gewicht: 500, kursiv: false, groesse: 48, farbe: '#222222', x: 300, y: 375 });
    expect(GestaltungSchema.safeParse({ ...g, ebenen: [t] }).success).toBe(true);
    expect(neueTextEbene('e-2', g, {})).toMatchObject({ schrift: 'playfair', gewicht: 900, farbe: '#1C1B18' });
  });

  it('+ Bild passt hohe Bilder in die Flaeche', () => {
    const g = { ...neueGestaltung('#FFFFFF'), format: 'banner' as const };
    expect(neueBildEbene('b', g, 'a.png').breite).toBe(300);
    expect(neueBildEbene('b', g, 'a.png', 0.5).breite).toBe(80);
    expect(neueBildEbene('b', g, 'a.png').quelle).toBe('medien:a.png');
  });

  it('Ladenfarben aus root.data, benutzte als Vorschlag dazu', () => {
    const g = { ...neueGestaltung('#123456'), ebenen: [neueTextEbene('t', neueGestaltung('#FFFFFF'), root)] };
    expect(ladenfarben(root, g)).toEqual({ laden: ['#FAFAF7', '#EEEEEE', '#222222', '#C0392B'], benutzt: ['#123456'] });
  });

  it('Medien: freigestellte zuerst, keine Platzhalter und Entwuerfe', () => {
    expect(medienFuerEbenen(['a.jpg', 'platzhalter-2x1.png', 'b-frei.png', 'gs-aaaaaaaaaaaa.jpg', 'c.png'])).toEqual([
      'b-frei.png',
      'a.jpg',
      'c.png',
    ]);
  });

  it('Anzeige-Adresse und Namen', () => {
    expect(quelleAnzeige('medien:a b.png')).toBe('/medien/datei/a%20b.png');
    expect(ebenenName({ id: 'b', art: 'bild', quelle: 'medien:kopf-frei.png', x: 0, y: 0, breite: 10, drehung: 0 })).toBe('kopf-frei');
    expect(ebenenName(neueTextEbene('t', neueGestaltung('#FFFFFF'), {}))).toBe('Dein Text');
  });

  it('Formatwechsel haelt die Lage im Verhaeltnis', () => {
    const g = { ...neueGestaltung('#FFFFFF'), ebenen: [neueTextEbene('t', neueGestaltung('#FFFFFF'), {})] };
    expect(formatWechseln(g, 'quadrat').ebenen[0].y).toBe(300);
  });

  it('kaputte Gestaltung im Block wird eine neue Flaeche', () => {
    const r = flaecheLesen({ data: { props: { url: null, alt: 'X', gestaltung: { version: 2 } } } }, root);
    expect(r).toEqual({ g: neueGestaltung('#FAFAF7'), alt: 'X', hatBild: false });
  });

  it('Pruefgrund nennt die Ebene', () => {
    const t = { ...neueTextEbene('t', neueGestaltung('#FFFFFF'), {}), text: '  ' };
    const g = { ...neueGestaltung('#FFFFFF'), ebenen: [t] };
    const r = GestaltungSchema.safeParse(g);
    expect(r.success).toBe(false);
    if (!r.success) expect(pruefGrund(r.error, g)).toBe('Ebene „Text“: Text leer, zu lang oder mehr als 6 Zeilen');
  });
});
