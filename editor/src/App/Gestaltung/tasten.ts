// Wann wirken Entf, Pfeile und Strg+Z/Y auf die Flaeche? Nur wenn der Fokus auf der
// Fensterwurzel, der Buehne oder einer Ebenenzeile selbst liegt (alle mit data-tasten bzw.
// in data-buehne). Auf einem Select-Ausloeser (div[role=combobox]), einem Knopf, einem
// Eingabefeld oder einem Aufklapper gehoeren die Tasten dem Bedienelement - sonst loeschte
// Entf auf der Schriftauswahl die Ebene.
export type TastenZiel = { matches(s: string): boolean; closest(s: string): unknown } | null;

export function flaechenTaste(ziel: TastenZiel): boolean {
  if (ziel === null) return true; // Fokus nirgends (body)
  return ziel.matches('[data-tasten]') || ziel.closest('[data-buehne]') !== null;
}
