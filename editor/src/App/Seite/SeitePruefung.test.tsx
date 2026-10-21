import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { Befund } from '../../pult';
import { FARBE } from '../Gestaltung/gestaltungStil';

import SeitePruefung, {
  befundeOrdnen,
  befundeVeraltet,
  befundZusammenfassung,
  KEINE_BEFUNDE,
  veraltetText,
  type PruefStand,
} from './SeitePruefung';

const BEFUNDE: Befund[] = [
  { schwere: 'weich', punkt: 'seite', satz: 'Kein Knopf auf der Seite' },
  { schwere: 'hart', punkt: 'text1', satz: 'text1: Kontrast 2,1:1 auf dem Bild – mindestens 4,5:1' },
  { schwere: 'weich', punkt: 'weg', satz: 'weg: Fließtext 12 – mindestens 15' },
];

const leer = () => undefined;
const zeigen = (stand: PruefStand, veraltet = false) =>
  renderToStaticMarkup(
    <SeitePruefung stand={stand} veraltet={veraltet} ebenen={new Set(['text1', 'bild1'])} onWaehlen={leer} onSchliessen={leer} />,
  );

// MUI schreibt Farben als rgb(...) oder hex - hier reicht die Hex-Form im Stil.
function rgb(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

describe('Prüfung in der rechten Spalte', () => {
  it('harte Befunde zuerst in der Fehlerfarbe, weiche gedämpft', () => {
    const html = zeigen({ art: 'befunde', befunde: BEFUNDE, fassung: 4 });
    const hart = html.indexOf('Kontrast 2,1:1');
    expect(hart).toBeGreaterThan(-1);
    expect(hart).toBeLessThan(html.indexOf('Kein Knopf'));
    const farbeVon = (satz: string) => {
      const vor = html.slice(0, html.indexOf(satz));
      return vor.slice(vor.lastIndexOf('<'));
    };
    expect(html).toMatch(new RegExp(`(${FARBE.fehler}|${rgb(FARBE.fehler).replace(/[()]/g, '\$&')})`));
    expect(farbeVon('text1: Kontrast')).toMatch(/<button/);
    expect(farbeVon('Kein Knopf')).not.toMatch(/<button/);
    expect(html.match(/data-befund="hart"/g)?.length).toBe(1);
    expect(html.match(/data-befund="weich"/g)?.length).toBe(2);
  });

  it('nur Befunde zu vorhandenen Ebenen sind wählbar', () => {
    const html = zeigen({ art: 'befunde', befunde: BEFUNDE, fassung: 4 });
    expect(html.match(/<button[^>]*title="Ebene auswählen"/g)?.length).toBe(1);
  });

  it('ohne Befunde, beim Laden und bei Fehlern: Text', () => {
    expect(zeigen({ art: 'befunde', befunde: [], fassung: 4 })).toContain(KEINE_BEFUNDE);
    expect(zeigen({ art: 'laedt' })).toContain('Wird geprüft …');
    expect(zeigen({ art: 'fehler', grund: 'Chromium ist gerade beschäftigt' })).toContain('Chromium ist gerade beschäftigt');
  });

  it('Zusammenfassung und Reihenfolge', () => {
    expect(befundZusammenfassung(BEFUNDE)).toBe('1 harter Befund, 2 Hinweise');
    expect(befundZusammenfassung([BEFUNDE[1], BEFUNDE[1]])).toBe('2 harte Befunde');
    expect(befundZusammenfassung([BEFUNDE[0]])).toBe('1 Hinweis');
    expect(befundZusammenfassung([])).toBe('');
    expect(befundeOrdnen(BEFUNDE).map((b) => b.schwere)).toEqual(['hart', 'weich', 'weich']);
  });
});

describe('Prüfung: welche Fassung (Gesamtprüfung Stufe 5)', () => {
  it('nennt die geprüfte Fassung', () => {
    expect(zeigen({ art: 'befunde', befunde: BEFUNDE, fassung: 4 })).toContain('Prüfung · Fassung 4');
    expect(zeigen({ art: 'laedt' })).not.toContain('Fassung');
  });

  it('nach einer Änderung: Hinweis, dass die Befunde für die alte Fassung gelten', () => {
    const stand: PruefStand = { art: 'befunde', befunde: BEFUNDE, fassung: 4 };
    expect(befundeVeraltet(stand, false, 4)).toBe(false);
    expect(befundeVeraltet(stand, true, 4)).toBe(true);
    expect(befundeVeraltet(stand, false, 5)).toBe(true);
    expect(befundeVeraltet({ art: 'laedt' }, true, 4)).toBe(false);
    expect(zeigen(stand)).not.toContain('data-veraltet');
    const html = zeigen(stand, true);
    expect(html).toContain('data-veraltet');
    expect(html).toContain(veraltetText(4));
    expect(veraltetText(4)).toBe('Die Seite wurde seither geändert – die Befunde gelten für Fassung 4. Bitte erneut prüfen.');
  });
});
