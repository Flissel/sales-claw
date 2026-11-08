// Ebenen der Kalenderseite: eine Farbe und ein Schalter je Kalender. Reine
// Funktionen plus ein kleiner Speicher; die Seite laeuft auch ohne localStorage.

/** Feste Palette (gut unterscheidbar, ohne Rot/Gruen-Paar als einziges Merkmal). */
export const PALETTE: readonly string[] = [
  '#2563eb', '#4d7c5a', '#c2410c', '#7c3aed', '#0e7490', '#be185d', '#a16207', '#475569',
];

const SCHLUESSEL = 'vk-ebenen-aus';

export function farbeFuer(_ebeneId: string, index: number): string {
  return PALETTE[((index % PALETTE.length) + PALETTE.length) % PALETTE.length];
}

export function ausgeschaltet(): Set<string> {
  try {
    const roh = globalThis.localStorage.getItem(SCHLUESSEL);
    const liste: unknown = roh ? JSON.parse(roh) : [];
    return new Set(Array.isArray(liste) ? liste.filter((x): x is string => typeof x === 'string') : []);
  } catch {
    return new Set();
  }
}

export function umschalten(id: string): void {
  const aus = ausgeschaltet();
  if (aus.has(id)) aus.delete(id);
  else aus.add(id);
  try {
    globalThis.localStorage.setItem(SCHLUESSEL, JSON.stringify([...aus]));
  } catch {
    /* Speicher gesperrt - die Wahl gilt dann nur bis zum Neuladen */
  }
}

export function filtern<T extends { extendedProps?: { ebene?: unknown } }>(events: T[], aus: Set<string>): T[] {
  return events.filter((e) => !aus.has(String(e.extendedProps?.ebene ?? '')));
}
