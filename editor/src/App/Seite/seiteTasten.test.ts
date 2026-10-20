import { describe, expect, it, vi } from 'vitest';

import type { Seite } from '../../seite';

import { seiteTaste, type SeiteTasteEreignis } from './seiteTasten';

const seite: Seite = {
  version: 1, breite: 600, hoehe: 800, hintergrund: { farbe: '#ffffff', bild: null },
  schriften: { anzeige: 'dm-sans', text: 'dm-sans' },
  ebenen: [{ id: 'f', art: 'form', form: 'rechteck', farbe: '#000000', x: 300, y: 200, breite: 100, hoehe: 50 }],
};

function zustand(auswahl: string | null = 'f') {
  return {
    auswahl,
    waehlen: vi.fn(),
    zurueck: vi.fn(),
    vor: vi.fn(),
    loeschen: vi.fn(),
    ebeneAendern: vi.fn(),
    aktuell: () => seite,
  };
}

const taste = (key: string, mehr: Partial<SeiteTasteEreignis> = {}): SeiteTasteEreignis => ({
  key, ctrlKey: false, metaKey: false, shiftKey: false, preventDefault: vi.fn(), ...mehr,
});

const ziel = (feld: boolean, flaeche: boolean) => ({
  matches: (sel: string) => (sel.includes('textarea') ? feld : flaeche),
  closest: () => (flaeche ? {} : null),
});

describe('seiteTaste', () => {
  it('Pfeile schieben die Auswahl (Umschalt = 10) als gleitender Schritt', () => {
    const z = zustand();
    seiteTaste(taste('ArrowRight'), null, z);
    expect(z.ebeneAendern).toHaveBeenCalledWith('f', { x: 301, y: 200 }, 'gleiten');
    seiteTaste(taste('ArrowUp', { shiftKey: true }), null, z);
    expect(z.ebeneAendern).toHaveBeenLastCalledWith('f', { x: 300, y: 190 }, 'gleiten');
  });

  it('Entf löscht, Strg+Z / Strg+Y / Strg+Umschalt+Z, Esc hebt die Auswahl auf', () => {
    const z = zustand();
    seiteTaste(taste('Delete'), null, z);
    expect(z.loeschen).toHaveBeenCalledWith('f');
    seiteTaste(taste('z', { ctrlKey: true }), null, z);
    expect(z.zurueck).toHaveBeenCalledTimes(1);
    seiteTaste(taste('y', { ctrlKey: true }), null, z);
    seiteTaste(taste('Z', { ctrlKey: true, shiftKey: true }), null, z);
    expect(z.vor).toHaveBeenCalledTimes(2);
    seiteTaste(taste('Escape'), null, z);
    expect(z.waehlen).toHaveBeenCalledWith(null);
  });

  it('in Eingabefeldern und außerhalb der Fläche gehören die Tasten dem Bedienelement', () => {
    const z = zustand();
    seiteTaste(taste('Delete'), ziel(true, true), z);
    seiteTaste(taste('Delete'), ziel(false, false), z);
    expect(z.loeschen).not.toHaveBeenCalled();
    seiteTaste(taste('Delete'), ziel(false, true), z);
    expect(z.loeschen).toHaveBeenCalledTimes(1);
  });

  it('ohne Auswahl tun Pfeile und Entf nichts', () => {
    const z = zustand(null);
    seiteTaste(taste('Delete'), null, z);
    seiteTaste(taste('ArrowLeft'), null, z);
    expect(z.loeschen).not.toHaveBeenCalled();
    expect(z.ebeneAendern).not.toHaveBeenCalled();
  });
});
