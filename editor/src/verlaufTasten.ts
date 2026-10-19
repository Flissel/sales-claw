// Tasten fuer Rueckgaengig/Wiederholen im Newsletter (Plan 2026-10-19 E11): Strg/Cmd+Z,
// Strg/Cmd+Umschalt+Z und Strg+Y - nie in Textfeldern (dort gilt das Rueckgaengig des Browsers)
// und nicht, solange der Editor gesperrt ist (Assistent arbeitet, liegt zur Freigabe).
type Ziel = { tagName?: string; isContentEditable?: boolean; closest?: (s: string) => unknown };
export type VerlaufTaste = {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  target: unknown;
};

function inTextfeld(ziel: unknown): boolean {
  if (typeof ziel !== 'object' || ziel === null) return false;
  const z = ziel as Ziel;
  const tag = (z.tagName ?? '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (z.isContentEditable) return true;
  return typeof z.closest === 'function' && z.closest('[contenteditable]:not([contenteditable="false"])') != null;
}

export function verlaufTaste(ev: VerlaufTaste, gesperrt: boolean): 'rueckgaengig' | 'wiederholen' | null {
  if (gesperrt || ev.altKey || !(ev.ctrlKey || ev.metaKey) || inTextfeld(ev.target)) return null;
  const k = ev.key.toLowerCase();
  if (k === 'z') return ev.shiftKey ? 'wiederholen' : 'rueckgaengig';
  if (k === 'y' && ev.ctrlKey && !ev.shiftKey) return 'wiederholen';
  return null;
}
