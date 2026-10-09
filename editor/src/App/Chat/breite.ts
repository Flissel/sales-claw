// Breite der rechten Leiste mit dem Editor-Chat (Spec 2026-10-09-editor-parallele-runden §2): Start 440 px,
// ziehbar zwischen 360 px und der halben Fensterbreite, je Browser gemerkt. Ohne Speicher gilt die Vorgabe.
export const BREITE_START = 440;
export const BREITE_MIN = 360;
export const BREITE_SCHLUESSEL = 'vibemind.editor.chatbreite';

export function fensterBreite(): number {
  const w = typeof window !== 'undefined' ? window.innerWidth : NaN;
  return Number.isFinite(w) && w > 0 ? w : 1280;
}

export function breiteBegrenzen(px: number, fenster: number): number {
  const max = Math.max(BREITE_MIN, Math.floor((Number.isFinite(fenster) ? fenster : 1280) / 2));
  const wert = Number.isFinite(px) ? Math.round(px) : BREITE_START;
  return Math.min(max, Math.max(BREITE_MIN, wert));
}

export function breiteLesen(fenster: number): number {
  try {
    const roh = globalThis.localStorage?.getItem(BREITE_SCHLUESSEL);
    const n = roh == null || roh.trim() === '' ? NaN : Number(roh);
    return breiteBegrenzen(n, fenster);
  } catch {
    return breiteBegrenzen(BREITE_START, fenster);
  }
}

export function breiteSchreiben(px: number): void {
  try {
    globalThis.localStorage?.setItem(BREITE_SCHLUESSEL, String(Math.round(px)));
  } catch {
    /* privates Fenster o. ae.: dann gilt beim naechsten Mal die Vorgabe */
  }
}
