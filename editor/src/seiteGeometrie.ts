// Reine Geometrie der Collagen-Flaeche (kein DOM). Einheit: Seiteneinheiten, 600 breit.
// x/y = Mittelpunkt, drehung positiv = im Uhrzeigersinn (CSS, y zeigt nach unten).
import { BREITE, HOEHE_MAX, HOEHE_MIN, type Seite, type SeitenEbene } from './seite';

const klemme = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));
const RAD = Math.PI / 180;

/** Normalisiert einen Winkel auf -180..180. */
function normalisiert(grad: number): number {
  return ((((grad + 180) % 360) + 360) % 360) - 180;
}

export function klemmen(e: SeitenEbene): SeitenEbene {
  return {
    ...e,
    x: klemme(e.x, -600, 1200),
    y: klemme(e.y, -1000, 7000),
    breite: klemme(e.breite, 1, 1200),
    hoehe: klemme(e.hoehe, 1, 6000),
    drehung: normalisiert(e.drehung ?? 0),
  };
}

export type Linie = { art: 'senkrecht' | 'waagrecht'; wert: number };

function rastenAchse(
  mitte: number,
  groesse: number,
  ziele: number[],
  schwelle: number
): { wert: number; linie: number | null } {
  let best: { d: number; ziel: number } | null = null;
  for (const punkt of [mitte - groesse / 2, mitte, mitte + groesse / 2]) {
    for (const ziel of ziele) {
      const d = ziel - punkt;
      if (Math.abs(d) <= schwelle && (best === null || Math.abs(d) < Math.abs(best.d))) best = { d, ziel };
    }
  }
  return best ? { wert: mitte + best.d, linie: best.ziel } : { wert: mitte, linie: null };
}

/** Rastet Mittelpunkt und Kanten an Seitenrand, Seitenmitte sowie Mitten/Kanten anderer Ebenen. */
export function einrastenSeite(
  e: SeitenEbene,
  andere: SeitenEbene[],
  hoehe: number,
  schwelle = 6
): { x: number; y: number; linien: Linie[] } {
  const zx = [0, BREITE / 2, BREITE];
  const zy = [0, hoehe / 2, hoehe];
  for (const a of andere) {
    if (a.id === e.id) continue;
    zx.push(a.x - a.breite / 2, a.x, a.x + a.breite / 2);
    zy.push(a.y - a.hoehe / 2, a.y, a.y + a.hoehe / 2);
  }
  const rx = rastenAchse(e.x, e.breite, zx, schwelle);
  const ry = rastenAchse(e.y, e.hoehe, zy, schwelle);
  const linien: Linie[] = [];
  if (rx.linie !== null) linien.push({ art: 'senkrecht', wert: rx.linie });
  if (ry.linie !== null) linien.push({ art: 'waagrecht', wert: ry.linie });
  return { x: rx.wert, y: ry.wert, linien };
}

export type Griff = 'no' | 'nw' | 'so' | 'sw' | 'n' | 's' | 'o' | 'w';

/**
 * Groesse aendern, die gegenueberliegende Kante bleibt in Seitenkoordinaten stehen.
 * dx/dy sind Mausbewegung in Seiteneinheiten; sie werden um -drehung in den Ebenenrahmen gedreht.
 */
export function griffZiehen(
  e: SeitenEbene,
  griff: Griff,
  dx: number,
  dy: number,
  festesVerhaeltnis: boolean
): SeitenEbene {
  const r = (e.drehung ?? 0) * RAD;
  const ldx = dx * Math.cos(-r) - dy * Math.sin(-r);
  const ldy = dx * Math.sin(-r) + dy * Math.cos(-r);
  const sx = griff.includes('o') ? 1 : griff.includes('w') ? -1 : 0;
  const sy = griff.includes('s') ? 1 : griff.includes('n') ? -1 : 0;
  let b = klemme(e.breite + sx * ldx, 1, 1200);
  let h = klemme(e.hoehe + sy * ldy, 1, 6000);
  if (festesVerhaeltnis) {
    // Ein gemeinsamer Faktor, gegen die Grenzen BEIDER Seiten geklemmt: Verhaeltnis und feste Kante bleiben.
    const wunsch = sx !== 0 && sy !== 0 ? Math.max(b / e.breite, h / e.hoehe) : sx !== 0 ? b / e.breite : h / e.hoehe;
    const f = klemme(wunsch, Math.max(1 / e.breite, 1 / e.hoehe), Math.min(1200 / e.breite, 6000 / e.hoehe));
    b = e.breite * f;
    h = e.hoehe * f;
  }
  // Mittelpunktverschiebung im Ebenenrahmen, dann um +drehung zurueck in Seitenkoordinaten.
  const mx = (sx * (b - e.breite)) / 2;
  const my = (sy * (h - e.hoehe)) / 2;
  const x = e.x + mx * Math.cos(r) - my * Math.sin(r);
  const y = e.y + mx * Math.sin(r) + my * Math.cos(r);
  return klemmen({ ...e, breite: b, hoehe: h, x, y });
}

export function drehenZu(e: SeitenEbene, mausX: number, mausY: number, einrasten15: boolean): SeitenEbene {
  let w = Math.atan2(mausY - e.y, mausX - e.x) / RAD;
  if (einrasten15) w = Math.round(w / 15) * 15;
  return klemmen({ ...e, drehung: w });
}

export function hoeheZiehen(s: Seite, neueHoehe: number): Seite {
  return { ...s, hoehe: klemme(Math.round(neueHoehe), HOEHE_MIN, HOEHE_MAX) };
}
