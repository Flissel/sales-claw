// Ebenen der Kalenderseite: eine Farbe und ein Schalter je Kalender. Reine
// Funktionen plus ein kleiner Speicher; die Seite laeuft auch ohne localStorage.

/** Feste Palette (gut unterscheidbar, ohne Rot/Gruen-Paar als einziges Merkmal).
 *  Ohne Blau, Bernstein/Orange und Grau: die gehoeren den festen Ebenen
 *  (Eigene Termine, Kundentermine, Laden-Kalender) in abbild.FARBEN. */
export const PALETTE: readonly string[] = [
  '#4d7c5a', '#7c3aed', '#0e7490', '#be185d', '#475569', '#b91c1c', '#ca8a04', '#57534e',
];

const SCHLUESSEL = 'vk-ebenen-aus';

export function farbeFuer(_ebeneId: string, index: number): string {
  return PALETTE[((index % PALETTE.length) + PALETTE.length) % PALETTE.length];
}

// Hauptzustand im Speicher: der Schalter wirkt auch, wenn localStorage gesperrt ist.
// localStorage ist nur Ablage - einmal geladen, danach best effort geschrieben.
let aus: Set<string> | null = null;

function laden(): Set<string> {
  try {
    const roh = globalThis.localStorage.getItem(SCHLUESSEL);
    const liste: unknown = roh ? JSON.parse(roh) : [];
    return new Set(Array.isArray(liste) ? liste.filter((x): x is string => typeof x === 'string') : []);
  } catch {
    return new Set();
  }
}

export function ausgeschaltet(): Set<string> {
  if (aus === null) aus = laden();
  return new Set(aus);
}

/** Nur fuer Tests: Speicherstand verwerfen, beim naechsten Zugriff neu laden. */
export function zuruecksetzen(): void {
  aus = null;
}

export function umschalten(id: string): void {
  const neu = ausgeschaltet();
  if (neu.has(id)) neu.delete(id);
  else neu.add(id);
  aus = neu;
  try {
    globalThis.localStorage.setItem(SCHLUESSEL, JSON.stringify([...neu]));
  } catch {
    /* Speicher gesperrt - die Wahl gilt dann bis zum Neuladen der Seite */
  }
}

export function filtern<T extends { extendedProps?: { ebene?: unknown } }>(events: T[], aus: Set<string>): T[] {
  return events.filter((e) => !aus.has(String(e.extendedProps?.ebene ?? '')));
}
