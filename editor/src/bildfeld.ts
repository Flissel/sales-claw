// Reine Hilfen fuer das Bildfeld (Spec 2026-09-29-newsletter-bilder §8). Die
// Rechnung von formatText entspricht spaces/marketing/claw/bildplaetze.py.
// Bewusst ohne Wert-Imports aus anderen src-Modulen (node --test laedt die Datei direkt).
export type Auftrag = { platz: string | null; status: string; befund?: string; hinweis?: string; nur_leere?: boolean };

const UEBLICH: [number, number][] = [[1, 1], [2, 1], [3, 1], [4, 3], [3, 2], [16, 9], [3, 4], [2, 3], [9, 16]];
const ggt = (a: number, b: number): number => (b ? ggt(b, a % b) : a);
const auf16 = (x: number) => Math.max(16, Math.ceil(x / 16) * 16);

export function verhaeltnis(w: number, h: number): [number, number] {
  const g = ggt(Math.round(w), Math.round(h)) || 1;
  let a = Math.round(w) / g, b = Math.round(h) / g;
  if (a > 21 || b > 21) [a, b] = UEBLICH.reduce((best, v) => (Math.abs(v[0] / v[1] - w / h) < Math.abs(best[0] / best[1] - w / h) ? v : best));
  return [a, b];
}

export function formatText(width: number, height: number): string {
  const eb = auf16(width * 2);
  const eh = auf16((eb * height) / width);
  const [a, b] = verhaeltnis(width, height);
  return `${a}:${b} · ${eb}×${eh}`;
}

export function istPlatz(p: { width?: unknown; height?: unknown } | null | undefined): boolean {
  return !!p && typeof p.width === 'number' && p.width > 0 && typeof p.height === 'number' && p.height > 0;
}

const PLATZHALTER = /(^medien:|\/medien\/datei\/)platzhalter-\d{1,3}x\d{1,3}\.png$/;
export function istLeer(url: string | null | undefined): boolean {
  return !url || !url.trim() || PLATZHALTER.test(url);
}

const TEXT: Record<string, [string, 'wartet' | 'laeuft']> = { offen: ['wartet (PC muss laufen)', 'wartet'], in_arbeit: ['wird erzeugt', 'laeuft'] };

export function standFuer(platz: string, auftraege: Auftrag[]): { text: string; art: 'wartet' | 'laeuft' | 'fehler' | null } {
  const meine = auftraege.filter((a) => a.platz === platz || a.platz === null);
  const laufend = meine.find((a) => a.status === 'offen' || a.status === 'in_arbeit');
  if (laufend) return { text: TEXT[laufend.status][0], art: TEXT[laufend.status][1] };
  const neuester = meine.find((a) => a.platz === platz && a.status !== 'verworfen');
  if (neuester?.status === 'fehler') return { text: `fehlgeschlagen: ${neuester.befund ?? ''}`.trim(), art: 'fehler' };
  return { text: '', art: null };
}

export function erzeugenSperre(ungespeichert: boolean, props: { width?: unknown; height?: unknown } | undefined): string | null {
  if (!istPlatz(props)) return 'Kein Bildplatz – Breite und Höhe setzen';
  if (ungespeichert) return 'Erst speichern – dieser Platz ist noch nicht gespeichert';
  return null;
}
