// Reine Hilfen des Gestaltungsfensters (ohne React): Vorgaben fuer neue Ebenen,
// Ladenfarben, Medienreihenfolge, Namen und verstaendliche Pruefgruende.
import type { ZodError } from 'zod';

import { BildEbene, Ebene, Format, Gestaltung, hoehe, neueGestaltung, TextEbene, BREITE } from '../../gestaltung';
import { ANZEIGE } from '../../pult';
import { GestaltungSchema, SCHNITTE, SCHRIFT_IDS, SchriftId } from '../../schemata';

const FARBE = /^#[0-9a-fA-F]{6}$/;

function obj(v: unknown): Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function rootDaten(root: unknown): Record<string, unknown> {
  return obj(obj(root).data);
}

export function istSchrift(id: unknown): id is SchriftId {
  return typeof id === 'string' && (SCHRIFT_IDS as readonly string[]).includes(id);
}

// Ebenen-Quellen bleiben "medien:<name>"; angezeigt wird ueber die Medien-Adresse.
export function quelleAnzeige(quelle: string): string {
  return quelle.startsWith('medien:') ? ANZEIGE + encodeURIComponent(quelle.slice(7)) : quelle;
}

// Hintergrund einer neuen Flaeche: die Layout-Flaeche des Newsletters.
export function flaechenHintergrund(root: unknown): string {
  const c = rootDaten(root).canvasColor;
  return typeof c === 'string' && FARBE.test(c) ? c.toUpperCase() : '#FFFFFF';
}

// Farben aus root.data (Layout + Rollen der Ladenmarke) und bereits in der Flaeche benutzte.
export function ladenfarben(root: unknown, g: Gestaltung): { laden: string[]; benutzt: string[] } {
  const d = rootDaten(root);
  const roh = [d.canvasColor, d.backdropColor, d.textColor, d.borderColor, ...Object.values(obj(d.rollen))];
  const laden = [...new Set(roh.filter((f): f is string => typeof f === 'string' && FARBE.test(f)).map((f) => f.toUpperCase()))];
  const eigene = [g.hintergrund, ...g.ebenen.flatMap((e) => (e.art === 'text' ? [e.farbe] : []))].map((f) => f.toUpperCase());
  const benutzt = [...new Set(eigene)].filter((f) => !laden.includes(f));
  return { laden, benutzt };
}

export function neueTextEbene(id: string, g: Gestaltung, root: unknown): TextEbene {
  const d = rootDaten(root);
  const anzeige = obj(d.schriften).anzeige;
  const schrift: SchriftId = istSchrift(anzeige) ? anzeige : 'playfair';
  const [gewicht, kursiv] = SCHNITTE[schrift][0];
  const tc = d.textColor;
  return {
    id,
    art: 'text',
    text: 'Dein Text',
    schrift,
    gewicht,
    kursiv,
    groesse: 48,
    farbe: typeof tc === 'string' && FARBE.test(tc) ? tc.toUpperCase() : '#1C1B18',
    ausrichtung: 'mitte',
    zeilenabstand: 1.2,
    x: BREITE / 2,
    y: hoehe(g.format) / 2,
    drehung: 0,
  };
}

// verhaeltnis = Breite/Hoehe des Bildes, falls bekannt: das Bild passt dann ganz in die Flaeche.
export function neueBildEbene(id: string, g: Gestaltung, name: string, verhaeltnis?: number): BildEbene {
  const h = hoehe(g.format);
  let breite = BREITE / 2;
  if (verhaeltnis && Number.isFinite(verhaeltnis) && verhaeltnis > 0) breite = Math.min(breite, h * 0.8 * verhaeltnis);
  return { id, art: 'bild', quelle: 'medien:' + name, x: BREITE / 2, y: h / 2, breite: Math.max(8, Math.round(breite)), drehung: 0 };
}

// Medienauswahl: keine Platzhalter und keine Entwurfsbilder, freigestellte zuerst.
export function medienFuerEbenen(liste: string[]): string[] {
  const nutzbar = liste.filter((n) => !n.startsWith('platzhalter-') && !n.startsWith('gs-'));
  const frei = nutzbar.filter(istFreigestellt);
  return [...frei, ...nutzbar.filter((n) => !istFreigestellt(n))];
}

export function istFreigestellt(name: string): boolean {
  return name.endsWith('-frei.png');
}

export function ebenenName(e: Ebene): string {
  if (e.art === 'bild') return e.quelle.replace(/^medien:/, '').replace(/\.[a-z]+$/i, '');
  const zeile = e.text.split('\n')[0].trim();
  const z = [...zeile];
  return z.length === 0 ? 'Text' : z.length > 28 ? z.slice(0, 27).join('') + '…' : zeile;
}

const GEWICHT: Record<number, string> = { 300: 'Light', 400: 'Regular', 500: 'Medium', 600: 'Semibold', 700: 'Bold', 900: 'Black' };
export function schnittName(gewicht: number, kursiv: boolean): string {
  return `${GEWICHT[gewicht] ?? gewicht}${kursiv ? ' Kursiv' : ''}`;
}

// Formatwechsel: Ebenen behalten ihre Lage im Verhaeltnis zur Hoehe.
export function formatWechseln(g: Gestaltung, f: Format): Gestaltung {
  if (f === g.format) return g;
  const k = hoehe(f) / hoehe(g.format);
  return { ...g, format: f, ebenen: g.ebenen.map((e) => ({ ...e, y: Math.round(e.y * k * 10) / 10 })) };
}

// Gestaltung und Alt-Text eines Bild-Blocks; fehlt oder ist kaputt -> neue Flaeche.
export function flaecheLesen(block: unknown, root: unknown): { g: Gestaltung; alt: string; hatBild: boolean } {
  const props = obj(obj(obj(block).data).props);
  const r = GestaltungSchema.safeParse(props.gestaltung);
  return {
    g: r.success ? (r.data as Gestaltung) : neueGestaltung(flaechenHintergrund(root)),
    alt: typeof props.alt === 'string' ? props.alt : '',
    hatBild: typeof props.url === 'string' && props.url !== '',
  };
}

const FELD: Record<string, string> = {
  text: 'Text leer, zu lang oder mehr als 6 Zeilen',
  groesse: 'Größe 10–160',
  zeilenabstand: 'Zeilenabstand 0,8–2,0',
  drehung: 'Drehung −180…180°',
  farbe: 'Farbe ungültig',
  breite: 'Breite 8–3000',
  x: 'liegt zu weit außerhalb',
  y: 'liegt zu weit außerhalb',
  quelle: 'Bildquelle ungültig',
};

// Erster Pruefgrund in Worten des Betreibers.
export function pruefGrund(fehler: ZodError, g: Gestaltung): string {
  const f = fehler.issues[0];
  if (!f) return 'Die Gestaltung ist ungültig';
  const [teil, i, feld] = f.path;
  if (teil === 'ebenen' && typeof i === 'number' && g.ebenen[i]) {
    const was = typeof feld === 'string' ? FELD[feld] ?? f.message : f.message === 'Schnitt der Schrift nicht vorhanden' ? f.message : 'ungültig';
    return `Ebene „${ebenenName(g.ebenen[i])}“: ${was}`;
  }
  if (teil === 'ebenen') return f.message === 'doppelte Ebenen-id' ? 'Zwei Ebenen haben dieselbe id' : 'Höchstens 20 Ebenen';
  if (teil === 'hintergrund') return 'Hintergrundfarbe ungültig';
  return 'Die Gestaltung ist ungültig';
}
