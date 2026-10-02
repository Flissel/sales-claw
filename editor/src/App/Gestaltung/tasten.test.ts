import { describe, expect, it } from 'vitest';

import { flaechenTaste } from './tasten';

// Kleines Stand-in fuer ein DOM-Element: matches/closest nach Selektor.
function el(eigene: string[], vorfahren: string[] = []) {
  return {
    matches: (s: string) => eigene.includes(s),
    closest: (s: string) => (eigene.includes(s) || vorfahren.includes(s) ? {} : null),
  };
}

describe('flaechenTaste', () => {
  it('Fensterwurzel, Buehne und Ebenenzeile duerfen', () => {
    expect(flaechenTaste(el(['[data-tasten]']))).toBe(true);
    expect(flaechenTaste(el([], ['[data-buehne]']))).toBe(true);
    expect(flaechenTaste(null)).toBe(true);
  });
  it('Select-Ausloeser, Knoepfe und Eingaben nicht', () => {
    expect(flaechenTaste(el([]))).toBe(false); // div[role=combobox], button, input …
    expect(flaechenTaste(el([], ['[data-tasten]']))).toBe(false); // Knopf in einer Ebenenzeile
  });
});
