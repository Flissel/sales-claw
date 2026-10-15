// Fertige Abschnitte zum Hineinziehen (Spec 2026-09-29-newsletter-bilder §8).
// Jeder Abschnitt ist ein Block auf oberster Ebene (Rahmen/Spalten nur dort,
// wie die DB verlangt) und bringt seine Bildplaetze mit Platzhalter mit.
import type { Dokument } from './pult';

// Gleicher Wert wie ANZEIGE in pult.ts; hier lokal, weil Node (Tests) eine
// Erweiterungslose Import-Adresse nicht aufloest und tsc keine ".ts"-Adressen erlaubt.
// Gleichlauf mit pult.ts wird in test/abschnitte.test.mjs geprueft.
const ANZEIGE = '/medien/datei/';

export type AbschnittSchluessel =
  | 'kopfbild' | 'bild_text' | 'zwei_spalten' | 'drei_spalten' | 'zitat' | 'grosse_zahl' | 'knopfleiste' | 'fussgruss'
  | 'brief' | 'portraet_gruss' | 'kundenstimme' | 'farbband' | 'einladung';
export type Farben = {
  text: string; hell: string; akzent: string; karte: string; grund: string; aufAkzent: string; akzentText: string;
};

export const ABSCHNITTE: { schluessel: AbschnittSchluessel; titel: string; beschreibung: string }[] = [
  { schluessel: 'kopfbild', titel: 'Kopfbild mit Titel', beschreibung: 'Großes Bild 2:1, Überschrift, Einleitung' },
  { schluessel: 'bild_text', titel: 'Bild neben Text', beschreibung: 'Bild 4:3 links, Text rechts' },
  { schluessel: 'zwei_spalten', titel: 'Zwei Spalten mit Bildern', beschreibung: 'Zwei Themen mit Bild 4:3' },
  { schluessel: 'drei_spalten', titel: 'Drei Spalten mit Bildern', beschreibung: 'Drei Punkte mit Bild 1:1' },
  { schluessel: 'zitat', titel: 'Zitat', beschreibung: 'Hervorgehobenes Zitat in einer Karte' },
  { schluessel: 'grosse_zahl', titel: 'Große Zahl', beschreibung: 'Eine Kennzahl mit Einordnung' },
  { schluessel: 'knopfleiste', titel: 'Knopfleiste', beschreibung: 'Satz und Knopf' },
  { schluessel: 'fussgruss', titel: 'Fußgruß', beschreibung: 'Trennlinie, Gruß, Link' },
  // Warme Abschnitte (Marketing-Befund 15.10.: die Newsletter wirkten herzlos und zu sehr wie ein Raster)
  { schluessel: 'brief', titel: 'Persönlicher Brief', beschreibung: 'Anrede, ein paar Sätze, Gruß mit Vornamen' },
  { schluessel: 'portraet_gruss', titel: 'Porträt mit Gruß', beschreibung: 'Rundes Foto, ein Satz, Vorname' },
  { schluessel: 'kundenstimme', titel: 'Kundenstimme', beschreibung: 'Rundes Foto, Zitat, Name' },
  { schluessel: 'farbband', titel: 'Farbband', beschreibung: 'Große Aussage über die ganze Breite' },
  { schluessel: 'einladung', titel: 'Einladung', beschreibung: 'Termin, Ort und Zusage-Knopf' },
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
  type: 'Heading', data: { style: { color, fontWeight: 'bold', textAlign: 'left', padding, fontFamily: 'ANZEIGE' }, props: { level, text } } });
const text = (t: string, fontSize: number, color: string, padding = PAD(0, 16), textAlign = 'left') => ({
  type: 'Text', data: { style: { color, fontSize, fontWeight: 'normal', textAlign, padding }, props: { text: t, markdown: true } } });
const knopf = (t: string, f: Farben, padding = PAD(8, 32), buttonStyle = 'rounded', textAlign = 'left') => ({
  type: 'Button', data: { style: { textAlign, padding, fontSize: 16 },
    props: { text: t, url: LINK, buttonBackgroundColor: f.akzent, buttonTextColor: f.aufAkzent, buttonStyle, size: 'large' } } });
// Satz in der Anzeigeschrift der Vorlage (Zitate); ohne Schriftpaar erbt er die Grundschrift.
const anzeige = <T extends { data: { style: Record<string, unknown> } }>(b: T): T =>
  ({ ...b, data: { ...b.data, style: { ...b.data.style, fontFamily: 'ANZEIGE' } } });
// Unterschrift in Handschrift (Rolle HAND = caveat, unabhaengig vom Schriftpaar).
const hand = <T extends { data: { style: Record<string, unknown> } }>(b: T): T =>
  ({ ...b, data: { ...b.data, style: { ...b.data.style, fontFamily: 'HAND' } } });
const portraet = (w: number, alt: string, padding = NULL, textAlign = 'center') => ({
  type: 'Image', data: { style: { padding, textAlign },
    props: { url: platzhalter(w, w), alt, width: w, height: w, contentAlignment: 'middle', form: 'kreis' } } });
const spalten = (listen: string[][], padding = PAD(0, 24, 24, 24)) => ({
  type: 'ColumnsContainer', data: { style: { padding }, props: {
    columnsCount: listen.length, columnsGap: 16, contentAlignment: 'top',
    columns: [...listen.map((childrenIds) => ({ childrenIds })), ...Array(3 - listen.length).fill(0).map(() => ({ childrenIds: [] as string[] }))] } } });
const rahmen = (kinder: string[], f: Farben) => ({
  type: 'Container', data: { style: { backgroundColor: f.karte, borderRadius: 12, padding: PAD(24, 24, 24, 24) },
    props: { childrenIds: kinder } } });

const FARBE = /^#[0-9a-fA-F]{6}$/;
const istFarbe = (w: unknown): w is string => typeof w === 'string' && FARBE.test(w);
const objekt = (w: unknown): Record<string, unknown> =>
  w && typeof w === 'object' && !Array.isArray(w) ? (w as Record<string, unknown>) : {};

// Wert an einem Rollen-Pfad wie "knopf/data/props/buttonBackgroundColor".
function wertAn(doc: Dokument, pfad: string): unknown {
  let x: unknown = doc;
  for (const teil of pfad.split('/')) x = objekt(x)[teil];
  return x;
}

const kanal = (f: string, i: number) => parseInt(f.slice(1 + 2 * i, 3 + 2 * i), 16);

// Mischt zwei #rrggbb; Runden mit floor(x + 0.5), damit der Marketing-Agent (Python) dasselbe rechnet.
export function mischen(a: string, b: string, anteil: number): string {
  return '#' + [0, 1, 2].map((i) => Math.floor(kanal(a, i) * (1 - anteil) + kanal(b, i) * anteil + 0.5)
    .toString(16).padStart(2, '0')).join('');
}

const dunkel = (f: string) => (0.2126 * kanal(f, 0) + 0.7152 * kanal(f, 1) + 0.0722 * kanal(f, 2)) / 255 < 0.4;

// Farben der Ladenmarke (root.data.rollen zeigt auf die gefuellten Werte); ohne Marke der erste Knopf,
// sonst der alte Petrol-Standard. Frueher waren hell/akzent/karte fest - auf hellen Vorlagen
// stand eine eingefuegte Ueberschrift dann fast weiss auf Beige.
export function farbenAus(doc: Dokument): Farben {
  const d = objekt(objekt(doc.root).data);
  const s = (k: string, std: string) => (istFarbe(d[k]) ? (d[k] as string).toLowerCase() : std);
  const rolle = (name: string) => {
    for (const [pfad, r] of Object.entries(objekt(d.rollen))) {
      const w = r === name ? wertAn(doc, pfad) : undefined;
      if (istFarbe(w)) return w.toLowerCase();
    }
    return undefined;
  };
  let knopf: string | undefined;
  for (const b of Object.values(doc)) {
    const w = objekt(objekt(objekt(b).data).props).buttonBackgroundColor;
    if (objekt(b).type === 'Button' && istFarbe(w)) { knopf = w.toLowerCase(); break; }
  }
  const text = s('textColor', '#cfe3df');
  const grund = s('canvasColor', '#0f2422');
  const akzent = rolle('akzent') ?? knopf ?? '#5eead4';
  return {
    text, grund, akzent,
    aufAkzent: rolle('auf_akzent') ?? grund,
    akzentText: rolle('akzent_text') ?? akzent,
    hell: dunkel(grund) ? mischen(text, '#ffffff', 0.6) : text,
    karte: mischen(grund, text, 0.06),
  };
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
      return { oben: hinein([neu(anzeige(text('„Ein Satz, der hängen bleibt.“', 20, f.hell, PAD(0, 8, 0, 0)))),
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
    case 'brief':
      return { oben: neu({ type: 'Container', data: { style: { padding: NULL }, props: { childrenIds: [
        neu(text('Hallo {vorname},', 20, f.akzentText, PAD(32, 12))),
        neu(text('Ein paar Sätze, so wie du sie am Ladentisch sagen würdest: was gerade neu ist, worauf du dich '
          + 'freust und warum du an deine Kundschaft gedacht hast.', 17, f.text, PAD(0, 16))),
        neu(text('Herzlich,', 17, f.text, PAD(0, 0))),
        neu(hand(text('Vorname', 30, f.akzentText, PAD(0, 32))))] } } }), bloecke: b };
    case 'portraet_gruss': {
      const l = [neu(portraet(140, 'Porträt der Inhaberin oder des Inhabers'))];
      const r = [neu(text('*„Ich packe jede Bestellung selbst ein – und lege manchmal etwas Kleines dazu.“*', 16, f.text,
        PAD(0, 4, 0, 0))), neu(hand(text('Vorname', 28, f.akzentText, PAD(0, 0, 0, 0)))),
        neu(text('Inhaberin', 13, f.text, NULL))];
      return { oben: neu({ type: 'ColumnsContainer', data: { style: { padding: PAD(28, 28, 32, 32), backgroundColor: f.karte },
        props: { columnsCount: 2, columnsGap: 24, contentAlignment: 'middle', fixedWidths: [140, null, null],
          columns: [{ childrenIds: l }, { childrenIds: r }, { childrenIds: [] }] } } }), bloecke: b };
    }
    case 'kundenstimme':
      return { oben: neu({ type: 'Container', data: { style: { backgroundColor: f.karte, borderRadius: 16, padding: PAD(28, 28, 32, 32) },
        props: { childrenIds: [neu(portraet(72, 'Foto der Kundin oder des Kunden', PAD(0, 12, 0, 0))),
          neu(anzeige(text('„Ein Satz, den eine Kundin wirklich gesagt hat.“', 20, f.hell, PAD(0, 8, 0, 0), 'center'))),
          neu(text('— Vorname, Stadt', 14, f.akzentText, NULL, 'center'))] } } }), bloecke: b };
    case 'farbband':
      return { oben: neu({ type: 'Container', data: { style: { backgroundColor: f.akzent, padding: PAD(48, 44, 40, 40) },
        props: { randlos: true, childrenIds: [
          neu(ueberschrift('Eine große Aussage.', 'h1', f.aufAkzent, PAD(0, 12, 0, 0))),
          neu(text('Ein Satz, der sie einordnet.', 18, f.aufAkzent, NULL))] } } }), bloecke: b };
    case 'einladung':
      return { oben: hinein([
        neu({ type: 'Text', data: { style: { color: f.akzentText, fontSize: 13, fontWeight: 'bold', textAlign: 'center',
          letterSpacing: 2, textTransform: 'uppercase', padding: PAD(0, 8, 0, 0) }, props: { text: 'Einladung' } } }),
        neu({ type: 'Heading', data: { style: { color: f.hell, fontWeight: 'bold', textAlign: 'center', padding: PAD(0, 8, 0, 0), fontFamily: 'ANZEIGE' },
          props: { level: 'h2', text: 'Ein Abend im Laden' } } }),
        neu(text('**Donnerstag, 18–21 Uhr**  \nMusterstraße 1 · mit Kaffee und Kuchen', 16, f.text, PAD(0, 16, 0, 0), 'center')),
        neu(knopf('Ich komme', f, NULL, 'pill', 'center'))]), bloecke: b };
  }
}

// Fester Satz Farb-Marken fuer die Golden-Datei: der Marketing-Agent (Python) ersetzt sie durch die
// Ladenfarben, die er mit derselben Regel wie farbenAus rechnet.
const MARKEN: Farben = { text: '{{text}}', hell: '{{hell}}', akzent: '{{akzent}}', karte: '{{karte}}', grund: '{{grund}}',
  aufAkzent: '{{aufAkzent}}', akzentText: '{{akzentText}}' };
const FARB_PROBEN = [
  { root: { type: 'EmailLayout', data: { canvasColor: '#0f2422', textColor: '#cfe3df', childrenIds: [] } } },
  { root: { type: 'EmailLayout', data: { canvasColor: '#FAF7F2', textColor: '#2b2724', childrenIds: ['k'],
    rollen: { 'k/data/props/buttonBackgroundColor': 'akzent', 'k/data/props/buttonTextColor': 'auf_akzent',
      'h/data/style/color': 'akzent_text' } } },
    k: { type: 'Button', data: { props: { buttonBackgroundColor: '#B5562F', buttonTextColor: '#ffffff' } } },
    h: { type: 'Heading', data: { style: { color: '#8f3f1f' } } } },
  { root: { type: 'EmailLayout', data: { canvasColor: '#ffffff', textColor: '#242424', childrenIds: ['t', 'k'] } },
    t: { type: 'Text', data: { props: { buttonBackgroundColor: '#123456' } } },
    k: { type: 'Button', data: { props: { buttonBackgroundColor: '#2f6f4f' } } } },
  { root: { type: 'EmailLayout', data: { canvasColor: '#1a1a1a', textColor: '#f0f0f0', childrenIds: [] } } },
] as unknown as Dokument[];

// Bauplaene und Farbregel als Daten fuer den Marketing-Agenten (test/abschnitte.golden.json).
export function golden() {
  const abschnitte: Record<string, unknown> = {};
  for (const { schluessel } of ABSCHNITTE) {
    let n = 0;
    abschnitte[schluessel] = bauen(schluessel, MARKEN, () => `n${++n}`);
  }
  return { anzeige: ANZEIGE, abschnitte, farben: FARB_PROBEN.map((doc) => ({ doc, erwartet: farbenAus(doc) })) };
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
