// Farben des Pults (sales-mcp/ui.py :root, hell und dunkel). Der Test
// test/pultfarben.test.mjs vergleicht sie mit ui.py - aendert sich das Pult,
// faellt er rot aus.
export const SCHRIFT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

export const HELL = {
  grund: '#f5f4f0', flaeche: '#ffffff', kopfzeile: '#f0eee8', aktiv: '#e4e1d9',
  schrift: '#1c1b18', gedaempft: '#5c574c', linie: '#d8d4cc', linie_stark: '#8a8578',
  balken: '#2f2a24', balken_schrift: '#f5f4f0', verweis: '#14507f',
  gut: '#1a6b43', info: '#1f5b7a', achtung: '#8a4b00', fehler: '#a01212',
} as const;

export const DUNKEL = {
  grund: '#171512', flaeche: '#26221d', kopfzeile: '#2a2721', aktiv: '#2e2a24',
  schrift: '#ece8e0', gedaempft: '#b0a99c', linie: '#4a443a', linie_stark: '#847d6e',
  balken: '#0d0c0a', balken_schrift: '#ece8e0', verweis: '#8cc0f0',
  gut: '#5fc98f', info: '#6fb6e0', achtung: '#e0a35c', fehler: '#ff8b8b',
} as const;

export type PultFarben = { [K in keyof typeof HELL]: string };
