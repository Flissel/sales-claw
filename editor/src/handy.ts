// Editor am Handy (Design-Review S4, 19.10.2026, E15): unter 768 px zeigt der
// Editor nur Vorschau und Assistent - Ziehen, Bloecke und Gestaltung bleiben Desktop.

// Dieselbe Grenze wie die Media-Queries von sales-ui (max-width: 767px).
export const HANDY_GRENZE = '(max-width:767.98px)';

// Pult-Vorschau einer gespeicherten Fassung, Vorgabe im Handy-Format (wie "Vorschau Handy" in der PultLeiste).
// Collagen zeigen live die Seite selbst (format=seite, billig); die Handy-Mail rendert Bildstücke in Chromium.
export function vorschauAdresse(vorschauUrl: string, basis: number, format: 'handy' | 'seite' = 'handy'): string {
  const trenner = vorschauUrl.includes('?') ? '&' : '?';
  return `${vorschauUrl}${trenner}fassung=${basis}&format=${format}`;
}
