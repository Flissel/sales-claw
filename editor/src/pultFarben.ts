// Farben des Pults (sales-mcp/ui.py :root, hell und dunkel). Der Test
// test/pultfarben.test.mjs vergleicht sie mit ui.py - aendert sich das Pult,
// faellt er rot aus.
export const SCHRIFT = '"DM Sans", system-ui, -apple-system, "Segoe UI", sans-serif';

export const HELL = {
  grund: '#f7f6fb', flaeche: '#ffffff', kopfzeile: '#f1eff8', aktiv: '#ece8fc',
  schrift: '#14121a', gedaempft: '#5d5872', linie: '#e2dfec', linie_stark: '#8a85a0',
  balken: '#14121a', balken_schrift: '#e8e5f3', verweis: '#4a30c0', akzent: '#5b3fd6',
  gut: '#1a6b43', info: '#1f5b7a', achtung: '#8a4b00', fehler: '#a01212',
} as const;

export const DUNKEL = {
  grund: '#121019', flaeche: '#1c1926', kopfzeile: '#221e2e', aktiv: '#2a2540',
  schrift: '#ece9f5', gedaempft: '#aaa4c0', linie: '#3a3550', linie_stark: '#77708f',
  balken: '#0b0a10', balken_schrift: '#e8e5f3', verweis: '#b5a6ff', akzent: '#9a86f5',
  gut: '#5fc98f', info: '#6fb6e0', achtung: '#e0a35c', fehler: '#ff8b8b',
} as const;

export type PultFarben = { [K in keyof typeof HELL]: string };
