import { describe, expect, it } from 'vitest';

import { BETREFF_MAX, betreffHinweis, VORSCHAU_MAX, vorschautextHinweis, zeichen } from './zaehler';

describe('Zähler für Betreff und Vorschautext', () => {
  it('Grenzen', () => {
    expect(BETREFF_MAX).toBe(60);
    expect(VORSCHAU_MAX).toBe(100);
  });

  it('Betreff: 60 Zeichen ohne Hinweis, 61 mit', () => {
    expect(betreffHinweis('x'.repeat(60))).toBeNull();
    expect(betreffHinweis('x'.repeat(61))).toBe('Mailprogramme kürzen ab etwa 60 Zeichen');
  });

  it('ein Emoji zählt als ein Zeichen, Ränder zählen nicht', () => {
    expect(zeichen('😀')).toBe(1);
    expect(zeichen('  ab  ')).toBe(2);
    expect(betreffHinweis('x'.repeat(59) + '😀')).toBeNull();
    expect(betreffHinweis('x'.repeat(60) + '😀')).not.toBeNull();
  });

  it('Vorschautext: leer, 100 und 101 Zeichen', () => {
    expect(vorschautextHinweis('  ')).toBe('Ohne Vorschautext zeigen Mailprogramme den Anfang der Mail');
    expect(vorschautextHinweis('')).toBe('Ohne Vorschautext zeigen Mailprogramme den Anfang der Mail');
    expect(vorschautextHinweis('x'.repeat(100))).toBeNull();
    expect(vorschautextHinweis('x'.repeat(101))).toBe('Mailprogramme zeigen etwa 40–100 Zeichen');
  });

  it('Betreff leer ist kein Längen-Hinweis', () => {
    expect(betreffHinweis('')).toBeNull();
  });
});
