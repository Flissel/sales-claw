// Fertige Abschnitte zum Hineinziehen (Spec 2026-09-29-newsletter-bilder §8).
// Jeder Abschnitt ist ein Block auf oberster Ebene (Rahmen/Spalten nur dort,
// wie die DB verlangt) und bringt seine Bildplaetze mit Platzhalter mit.
import type { Dokument } from './pult';

// Gleicher Wert wie ANZEIGE in pult.ts; hier lokal, weil Node (Tests) eine
// Erweiterungslose Import-Adresse nicht aufloest und tsc keine ".ts"-Adressen erlaubt.
const ANZEIGE = '/medien/datei/';

export type AbschnittSchluessel =
  | 'kopfbild' | 'bild_text' | 'zwei_spalten' | 'drei_spalten' | 'zitat' | 'grosse_zahl' | 'knopfleiste' | 'fussgruss';
export type Farben = { text: string; hell: string; akzent: string; karte: string; grund: string };

export const ABSCHNITTE: { schluessel: AbschnittSchluessel; titel: string; beschreibung: string }[] = [
  { schluessel: 'kopfbild', titel: 'Kopfbild mit Titel', beschreibung: 'Großes Bild 2:1, Überschrift, Einleitung' },
  { schluessel: 'bild_text', titel: 'Bild neben Text', beschreibung: 'Bild 4:3 links, Text rechts' },
  { schluessel: 'zwei_spalten', titel: 'Zwei Spalten mit Bildern', beschreibung: 'Zwei Themen mit Bild 4:3' },
  { schluessel: 'drei_spalten', titel: 'Drei Spalten mit Bildern', beschreibung: 'Drei Punkte mit Bild 1:1' },
  { schluessel: 'zitat', titel: 'Zitat', beschreibung: 'Hervorgehobenes Zitat in einer Karte' },
  { schluessel: 'grosse_zahl', titel: 'Große Zahl', beschreibung: 'Eine Kennzahl mit Einordnung' },
  { schluessel: 'knopfleiste', titel: 'Knopfleiste', beschreibung: 'Satz und Knopf' },
  { schluessel: 'fussgruss', titel: 'Fußgruß', beschreibung: 'Trennlinie, Gruß, Link' },
];

export const DRAG_TYP = 'application/x-vibemind-abschnitt';
const LINK = 'https://vibemind.space';
const PAD = (t: number, b: number, l = 40, r = 40) => ({ top: t, bottom: b, left: l, right: r });
const NULL = PAD(0, 0, 0, 0);

function platzhalter(w: number, h: number): string {
  const ggt = (a: number, b: number): number => (b ? ggt(b, a % b) : a);
  const g = ggt(w, h);
  return `${ANZEIGE}${encodeURIComponent(`platzhalter-${w / g}x${h / g}.png`)}`;
}

const bild = (w: number, h: number, alt: string, padding = NULL) => ({
  type: 'Image', data: { style: { padding, textAlign: 'center' },
    props: { url: platzhalter(w, h), alt, width: w, height: h, contentAlignment: 'middle' } } });
const ueberschrift = (text: string, level: 'h1' | 'h2' | 'h3', color: string, padding = PAD(0, 12)) => ({
  type: 'Heading', data: { style: { color, fontWeight: 'bold', textAlign: 'left', padding }, props: { level, text } } });
const text = (t: string, fontSize: number, color: string, padding = PAD(0, 16), textAlign = 'left') => ({
  type: 'Text', data: { style: { color, fontSize, fontWeight: 'normal', textAlign, padding }, props: { text: t, markdown: true } } });
const knopf = (t: string, f: Farben, padding = PAD(8, 32)) => ({
  type: 'Button', data: { style: { textAlign: 'left', padding, fontSize: 16 },
    props: { text: t, url: LINK, buttonBackgroundColor: f.akzent, buttonTextColor: f.grund, buttonStyle: 'rounded', size: 'large' } } });
const spalten = (listen: string[][], padding = PAD(0, 24, 24, 24)) => ({
  type: 'ColumnsContainer', data: { style: { padding }, props: {
    columnsCount: listen.length, columnsGap: 16, contentAlignment: 'top',
    columns: [...listen.map((childrenIds) => ({ childrenIds })), ...Array(3 - listen.length).fill(0).map(() => ({ childrenIds: [] as string[] }))] } } });
const rahmen = (kinder: string[], f: Farben) => ({
  type: 'Container', data: { style: { backgroundColor: f.karte, borderRadius: 12, padding: PAD(24, 24, 24, 24) },
    props: { childrenIds: kinder } } });

export function farbenAus(doc: Dokument): Farben {
  const d = ((doc.root as { data?: Record<string, unknown> } | undefined)?.data ?? {}) as Record<string, unknown>;
  const s = (k: string, std: string) => (typeof d[k] === 'string' ? (d[k] as string) : std);
  return { text: s('textColor', '#cfe3df'), grund: s('canvasColor', '#0f2422'), hell: '#e9fbf6', akzent: '#5eead4', karte: '#16302d' };
}

export function bauen(s: AbschnittSchluessel, f: Farben, neueId: () => string): { oben: string; bloecke: Record<string, unknown> } {
  const b: Record<string, unknown> = {};
  const neu = (block: unknown) => { const id = neueId(); b[id] = block; return id; };
  const hinein = (kinder: string[]) => neu(rahmen(kinder, f));
  switch (s) {
    case 'kopfbild': {
      // Der Abschnitt steckt in einem obersten Container; das Layout kappt Bilder darin auf 552 px.
      const kinder = [neu(bild(552, 276, 'Kopfbild zum Thema')), neu(ueberschrift('Überschrift', 'h1', f.hell, PAD(24, 12))),
        neu(text('Zwei, drei Sätze Einleitung.', 17, f.text))];
      return { oben: neu({ type: 'Container', data: { style: { padding: NULL }, props: { childrenIds: kinder } } }), bloecke: b };
    }
    case 'bild_text': {
      const l = [neu(bild(268, 201, 'Bild zum Text', NULL))];
      const r = [neu(ueberschrift('Thema', 'h3', f.hell, PAD(0, 8, 0, 0))), neu(text('Ein kurzer Absatz.', 15, f.text, PAD(0, 8, 0, 0)))];
      return { oben: neu(spalten([l, r])), bloecke: b };
    }
    case 'zwei_spalten':
    case 'drei_spalten': {
      const n = s === 'zwei_spalten' ? 2 : 3;
      const [w, h] = n === 2 ? [268, 201] : [172, 172];
      const listen = Array.from({ length: n }, (_, i) => [
        neu(bild(w, h, `Bild zu Punkt ${i + 1}`, PAD(0, 10, 0, 0))),
        neu(ueberschrift(`Punkt ${i + 1}`, 'h3', f.hell, PAD(0, 4, 0, 0))),
        neu(text('Ein Satz dazu.', 14, f.text, PAD(0, 0, 0, 0))),
      ]);
      return { oben: neu(spalten(listen)), bloecke: b };
    }
    case 'zitat':
      return { oben: hinein([neu(text('„Ein Satz, der hängen bleibt.“', 20, f.hell, PAD(0, 8, 0, 0))),
        neu(text('— Name, Rolle', 13, f.text, NULL))]), bloecke: b };
    case 'grosse_zahl':
      return { oben: hinein([neu(text('**3×** schneller', 34, f.akzent, PAD(0, 4, 0, 0), 'center')),
        neu(text('Ein Satz Einordnung.', 15, f.text, NULL, 'center'))]), bloecke: b };
    case 'knopfleiste':
      return { oben: neu({ type: 'Container', data: { style: { padding: NULL }, props: { childrenIds: [
        neu(text('Ein Satz, warum man klicken sollte.', 16, f.text, PAD(16, 8))), neu(knopf('Mehr erfahren', f))] } } }), bloecke: b };
    case 'fussgruss':
      return { oben: neu({ type: 'Container', data: { style: { padding: NULL }, props: { childrenIds: [
        neu({ type: 'Divider', data: { style: { padding: PAD(24, 16) }, props: { lineColor: '#2c4f4b', lineHeight: 1 } } }),
        neu(text('Bis bald,  \n**Felix** · VibeMind', 15, f.text, PAD(0, 8))),
        neu(text(`[vibemind.space](${LINK})`, 13, f.text, PAD(0, 40)))] } } }), bloecke: b };
  }
}

export function einfuegen(doc: Dokument, s: AbschnittSchluessel, index: number,
                          neueId: () => string = () => `a-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`): Dokument {
  const neu = JSON.parse(JSON.stringify(doc)) as Dokument;
  const belegt = new Set(Object.keys(neu));
  let zusatz = 0;
  const frei = () => { let id = neueId(); while (belegt.has(id)) id = `${id}-${++zusatz}`; belegt.add(id); return id; };
  const { oben, bloecke } = bauen(s, farbenAus(neu), frei);
  Object.assign(neu, bloecke);
  const root = neu.root as { data: { childrenIds?: string[] } };
  const kinder = [...(root.data.childrenIds ?? [])];
  kinder.splice(Math.max(0, Math.min(index, kinder.length)), 0, oben);
  root.data.childrenIds = kinder;
  return neu;
}
