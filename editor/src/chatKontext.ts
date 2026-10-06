// Kontext per Klick und Anhaenge im Gestaltungs-Chat (Spec 2026-10-06 §1, §2.1) - reine Regeln:
// Chips fuer markierte Bloecke/Ebenen und hochgeladene Dateien, und was davon mit der Nachricht
// als kontext.auswahl / kontext.anhaenge an das Pult geht (Pruefung dort: api/chat.py).

// Markierter Block (Newsletter) oder markierte Ebene (flaeche = Block-id der Gestaltungsflaeche).
export type AuswahlChip = { art: 'block' | 'ebene'; id: string; flaeche?: string; kurz: string };

// id: nur hier im Editor (zwei gleichnamige Dateien bleiben zwei Chips). name: waehrend des Uploads
// der Dateiname, danach der gespeicherte Name aus der Antwort. fortschritt 0..1.
export type AnhangChip = {
  id: string;
  name: string;
  art: 'bild' | 'dokument';
  status: 'laedt' | 'fertig' | 'fehler';
  grund?: string;
  fortschritt: number;
  vorschau?: string;
};

export type AuswahlKontext = { art: 'block' | 'ebene'; id: string; flaeche?: string; kurz: string };
export type AnhangKontext = { name: string; art: 'bild' | 'dokument' };

export const MAX_AUSWAHL = 8;
export const MAX_ANHAENGE = 5;
export const MAX_DATEI = 15 * 1024 * 1024;
// Das Pult laesst 80 zu; kurz gehalten, damit 8 Chips + 5 Anhaenge sicher unter 4 KB bleiben.
export const KURZ_MAX = 48;
const INHALT_MAX = 24;

const ID = /^[A-Za-z0-9_-]{1,64}$/;
const BILD = ['jpg', 'jpeg', 'png', 'webp'];
const DOKUMENT = ['pdf', 'docx', 'txt', 'md'];
export const DATEI_ANNAHME = [...BILD, ...DOKUMENT].map((e) => '.' + e).join(',');

const gleich = (a: AuswahlChip, b: AuswahlChip) => a.art === b.art && a.id === b.id && (a.flaeche ?? '') === (b.flaeche ?? '');

function kappen(text: string, max: number): string {
  const z = [...text];
  return z.length <= max ? text : z.slice(0, max - 1).join('').trimEnd() + '…';
}

// Neue Liste mit dem Chip; unveraendert (dieselbe Liste), wenn er schon drin ist, die Liste voll
// ist oder die id vom Pult abgelehnt wuerde.
export function chipHinzu(liste: AuswahlChip[], chip: AuswahlChip): AuswahlChip[] {
  if (!ID.test(chip.id) || (chip.flaeche !== undefined && !ID.test(chip.flaeche))) return liste;
  if (liste.length >= MAX_AUSWAHL || liste.some((c) => gleich(c, chip))) return liste;
  return [...liste, { ...chip, kurz: kappen(chip.kurz, KURZ_MAX) }];
}

// Erste nicht leere Zeile (Texte ohne Markdown-Zeichen, Dateinamen unveraendert), auf ein Wortende gekuerzt.
function anfang(text: string, markdown = true): string {
  const ohne = markdown ? text.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*_`#>~]/g, '') : text;
  const zeile =
    ohne
      .split('\n')
      .map((z) => z.trim())
      .find((z) => z !== '') ?? '';
  const z = [...zeile];
  if (z.length <= INHALT_MAX) return zeile;
  const stueck = z.slice(0, INHALT_MAX + 1).join('');
  const ende = stueck.lastIndexOf(' ');
  return (ende > 8 ? stueck.slice(0, ende) : z.slice(0, INHALT_MAX).join('')).trimEnd() + ' …';
}

function dateiStamm(quelle: string): string {
  let n = quelle.replace(/^medien:/, '');
  if (n.startsWith('/medien/datei/')) {
    try {
      n = decodeURIComponent(n.slice('/medien/datei/'.length));
    } catch {
      n = n.slice('/medien/datei/'.length);
    }
  }
  if (n.startsWith('data:') || n.includes('/')) return '';
  return n.replace(/\.[A-Za-z0-9]+$/, '');
}

const mit = (art: string, inhalt: string) => kappen(inhalt ? `${art} · ${inhalt}` : art, KURZ_MAX);

const BLOCK_ART: Record<string, string> = {
  Heading: 'Überschrift',
  Text: 'Text',
  Button: 'Knopf',
  Image: 'Bild',
  Divider: 'Trennlinie',
  Spacer: 'Abstand',
  Container: 'Rahmen',
  ColumnsContainer: 'Spalten',
};

type BlockArtig = { type: string; data?: unknown };
type EbeneArtig = { art: 'bild'; quelle: string } | { art: 'text'; text: string };

function istObjekt(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

// Kurztext fuer den Chip: "Überschrift · Goldener Herbst …", "Bild · held_bild", "Text-Ebene · Neu im Oktober".
export function kurzText(x: BlockArtig | EbeneArtig): string {
  if ('art' in x) {
    if (x.art === 'bild') return mit('Bild-Ebene', anfang(dateiStamm(x.quelle), false));
    return mit('Text-Ebene', anfang(x.text));
  }
  const props = istObjekt(x.data) && istObjekt(x.data.props) ? x.data.props : {};
  const text = (k: string) => (typeof props[k] === 'string' ? (props[k] as string) : '');
  if (x.type === 'Image') {
    const name = anfang(dateiStamm(text('url')), false);
    if (props.gestaltung) return mit('Fläche', anfang(text('alt')) || name);
    return mit('Bild', name || anfang(text('alt')));
  }
  return mit(BLOCK_ART[x.type] ?? 'Block', anfang(text('text')));
}

// Vorpruefung vor dem Upload (dieselben Grenzen wie die Anhang-Route).
export function dateiPruefen(f: { name: string; size: number }): { art: 'bild' | 'dokument' } | { grund: string } {
  const punkt = f.name.lastIndexOf('.');
  const endung = punkt > 0 ? f.name.slice(punkt + 1).toLowerCase() : '';
  const art = BILD.includes(endung) ? 'bild' : DOKUMENT.includes(endung) ? 'dokument' : null;
  if (art === null) return { grund: 'Dieser Typ geht nicht – Bilder (JPG, PNG, WebP) oder PDF, DOCX, TXT, MD' };
  if (f.size === 0) return { grund: 'Die Datei ist leer' };
  if (f.size > MAX_DATEI) return { grund: 'Größer als 15 MB' };
  return { art };
}

// Was mit der Nachricht geht: alle Chips (bis 8), nur fertig hochgeladene Anhaenge (bis 5).
export function kontextBauen(auswahl: AuswahlChip[], anhaenge: AnhangChip[]): { auswahl: AuswahlKontext[]; anhaenge: AnhangKontext[] } {
  return {
    auswahl: auswahl.slice(0, MAX_AUSWAHL).map((c) => (c.flaeche === undefined ? { art: c.art, id: c.id, kurz: c.kurz } : { art: c.art, id: c.id, flaeche: c.flaeche, kurz: c.kurz })),
    anhaenge: anhaenge
      .filter((a) => a.status === 'fertig')
      .slice(0, MAX_ANHAENGE)
      .map((a) => ({ name: a.name, art: a.art })),
  };
}

// Gibt es das markierte Element im Dokument noch? Bloecke: id vorhanden (nie root). Ebenen: die
// Flaeche ist noch eine Gestaltungsflaeche mit dieser Ebene. Die Flaeche `offen` wird nicht geprueft -
// ihr Fenster haelt ungesicherte Ebenen, die im Dokument noch fehlen.
function chipGibtEs(c: AuswahlChip, doc: Record<string, unknown>, offen: string | null): boolean {
  if (c.art === 'block') return c.id !== 'root' && istObjekt(doc[c.id]);
  if (c.flaeche === undefined) return false;
  if (c.flaeche === offen) return true;
  const block = doc[c.flaeche];
  const daten = istObjekt(block) && istObjekt(block.data) ? block.data : null;
  const props = daten && istObjekt(daten.props) ? daten.props : null;
  const g = props && istObjekt(props.gestaltung) ? props.gestaltung : null;
  return g !== null && Array.isArray(g.ebenen) && g.ebenen.some((e) => istObjekt(e) && e.id === c.id);
}

// Chips gegen das aktuelle Dokument; behalten = dieselbe Liste, wenn nichts wegfaellt.
export function chipsBereinigen(chips: AuswahlChip[], doc: Record<string, unknown>, offen: string | null): { behalten: AuswahlChip[]; entfernt: number } {
  const behalten = chips.filter((c) => chipGibtEs(c, doc, offen));
  return behalten.length === chips.length ? { behalten: chips, entfernt: 0 } : { behalten, entfernt: chips.length - behalten.length };
}

export function entferntHinweis(n: number): string {
  return n === 1 ? '1 markiertes Element gibt es nicht mehr – entfernt' : `${n} markierte Elemente gibt es nicht mehr – entfernt`;
}

// Groesse in Byte, wie das Pult sie misst: json.dumps(kontext, ensure_ascii=False) mit den
// Python-Trennern ", " und ": " (JSON.stringify schreibt sie ohne Leerzeichen).
export function kontextBytes(v: unknown): number {
  const text = (x: unknown): string => {
    if (Array.isArray(x)) return '[' + x.map(text).join(', ') + ']';
    if (istObjekt(x))
      return (
        '{' +
        Object.entries(x)
          .filter(([, w]) => w !== undefined)
          .map(([k, w]) => JSON.stringify(k) + ': ' + text(w))
          .join(', ') +
        '}'
      );
    return JSON.stringify(x) ?? 'null';
  };
  return new TextEncoder().encode(text(v)).length;
}

// Senden erst, wenn kein Upload mehr laeuft.
export function sendenErlaubt(anhaenge: AnhangChip[]): boolean {
  return !anhaenge.some((a) => a.status === 'laedt');
}
