// Gestaltungs-Modell der Newsletter-Flaeche: Typen und reine Mathematik (kein DOM).
// Einheit: 600 breit, Hoehe nach Format. Positives drehung = im Uhrzeigersinn (CSS).
export type Format = 'quer' | 'quadrat' | 'hoch' | 'banner';
export const FORMATE: Record<Format, [number, number]> = { quer: [3, 2], quadrat: [1, 1], hoch: [4, 5], banner: [3, 1] };
export const BREITE = 600;

export function hoehe(f: Format): number {
  const [a, b] = FORMATE[f];
  return Math.round((BREITE * b) / a);
}

export type BildEbene = { id: string; art: 'bild'; quelle: string; x: number; y: number; breite: number; drehung: number };
export type TextEbene = {
  id: string;
  art: 'text';
  text: string;
  schrift: string;
  gewicht: number;
  kursiv: boolean;
  groesse: number;
  farbe: string;
  ausrichtung: 'links' | 'mitte' | 'rechts';
  zeilenabstand: number;
  x: number;
  y: number;
  drehung: number;
};
export type Ebene = BildEbene | TextEbene;
export type Gestaltung = { version: 1; format: Format; hintergrund: string; ebenen: Ebene[] };

export function neueGestaltung(hintergrund: string): Gestaltung {
  return { version: 1, format: 'quer', hintergrund, ebenen: [] };
}

export function neueId(vorhanden: string[]): string {
  for (;;) {
    const id = 'e-' + Math.floor(Math.random() * 0x1000000).toString(16).padStart(6, '0');
    if (!vorhanden.includes(id)) return id;
  }
}

export function zoomFuer(platzB: number, platzH: number, f: Format): number {
  return Math.min(platzB / BREITE, platzH / hoehe(f), 2);
}

export function zuEinheit(px: number, py: number, zoom: number): { x: number; y: number } {
  return { x: px / zoom, y: py / zoom };
}

const klemme = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

export function skalieren(e: Ebene, deltaY: number): Ebene {
  const faktor = Math.pow(1.1, -deltaY / 100);
  return e.art === 'bild'
    ? { ...e, breite: klemme(e.breite * faktor, 8, 3000) }
    : { ...e, groesse: klemme(e.groesse * faktor, 10, 160) };
}

export function drehen(e: Ebene, deltaY: number): Ebene {
  const grad = Math.round(((((e.drehung + deltaY / 20 + 180) % 360) + 360) % 360) - 180);
  return { ...e, drehung: grad };
}

export function schieben(e: Ebene, dx: number, dy: number): Ebene {
  return { ...e, x: e.x + dx, y: e.y + dy };
}

export type Linie = { achse: 'x' | 'y'; wert: number };

function naechster(wert: number, kandidaten: number[], schwelle: number): number | null {
  let best: number | null = null;
  for (const k of kandidaten) {
    const d = Math.abs(k - wert);
    if (d <= schwelle && (best === null || d < Math.abs(best - wert))) best = k;
  }
  return best;
}

// x/y der Ebene sind ihre Mitte; die Groesse wird fuer das Einrasten der Mitte nicht gebraucht.
export function einrasten(
  e: Ebene,
  _groesse: { w: number; h: number },
  andere: Ebene[],
  f: Format,
  schwelle = 6
): { x: number; y: number; linien: Linie[] } {
  const h = hoehe(f);
  const sx = naechster(e.x, [0, BREITE / 2, BREITE, ...andere.map((o) => o.x)], schwelle);
  const sy = naechster(e.y, [0, h / 2, h, ...andere.map((o) => o.y)], schwelle);
  const linien: Linie[] = [];
  if (sx !== null) linien.push({ achse: 'x', wert: sx });
  if (sy !== null) linien.push({ achse: 'y', wert: sy });
  return { x: sx ?? e.x, y: sy ?? e.y, linien };
}

export function hinweise(g: Gestaltung): string[] {
  const out: string[] = [];
  for (const e of g.ebenen) {
    if (e.art === 'text' && e.groesse < 22) {
      out.push(`Text „${e.text.slice(0, 30)}“ ist am Handy unter 12 px`);
    }
  }
  return out;
}

const MAX_SCHRITTE = 100;

export function verlauf<T>(start: T): { jetzt(): T; setzen(v: T): void; zurueck(): boolean; vor(): boolean } {
  let stand: T[] = [start];
  let i = 0;
  return {
    jetzt: () => stand[i],
    setzen(v) {
      stand = [...stand.slice(0, i + 1), v];
      if (stand.length > MAX_SCHRITTE) stand = stand.slice(stand.length - MAX_SCHRITTE);
      i = stand.length - 1;
    },
    zurueck() {
      if (i === 0) return false;
      i -= 1;
      return true;
    },
    vor() {
      if (i >= stand.length - 1) return false;
      i += 1;
      return true;
    },
  };
}
