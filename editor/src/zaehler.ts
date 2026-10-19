// Zaehler fuer Betreff und Vorschautext (Plan 2026-10-19 E13): nur Hinweise, keine Sperre.
// Gezaehlt werden Schriftzeichen ohne Raender (ein Emoji = 1).
export const BETREFF_MAX = 60;
export const VORSCHAU_MAX = 100;

export function zeichen(text: string): number {
  return Array.from(text.trim()).length;
}

export function betreffHinweis(text: string): string | null {
  return zeichen(text) > BETREFF_MAX ? 'Mailprogramme kürzen ab etwa 60 Zeichen' : null;
}

export function vorschautextHinweis(text: string): string | null {
  const n = zeichen(text);
  if (n === 0) return 'Ohne Vorschautext zeigen Mailprogramme den Anfang der Mail';
  return n > VORSCHAU_MAX ? 'Mailprogramme zeigen etwa 40–100 Zeichen' : null;
}
