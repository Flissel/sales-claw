// Anbindung an den Gestaltungs-Agenten und den Export (Spec 2026-10-02 §4, §6):
// Chat senden/lesen, Rueckgaengig, Export-Vorschau und bestaetigter Export.
// Live-Lauf und mehrere Runden (Spec 2026-10-09-editor-parallele-runden §2): Stopp je Runde, Warteschlange.
// Nur relative Adressen aus den Startdaten; schreibende Aufrufe mit X-CSRF.
import type { AnhangKontext, AuswahlKontext } from './chatKontext';
import type { Dokument, Start } from './pult';

export type ExportAuswahl = { newsletter: boolean; flaechen: string[] };

export type SpurSchritt = { zeit: string; text: string };

export type ChatStatus = 'offen' | 'in_arbeit' | 'wartet' | 'fertig' | 'fehler';

export type StoppArt = 'behalten' | 'verwerfen';

export type ChatEintrag = {
  id: string;
  art: 'chat' | 'export';
  nachricht: string;
  antwort: string;
  status: ChatStatus;
  hinweise: string[];
  ergebnis: { export_vorschlag?: ExportAuswahl | null; notiz?: string };
  fassung_vorher: number | null;
  fassung_nachher: number | null;
  erstellt_am: string;
  denken: string;
  schritte: SpurSchritt[];
  // Live-Felder der Runde (gefuellt, solange sie laeuft) und gescheiterte Bildauftraege der Runde.
  schritt: string;
  schritt_nr: number;
  stopp: StoppArt | null;
  bild_hinweise: string[];
};

// Stand des laufenden Auftrags. zwischenstand im gespeicherten Format (medien:), null vor dem
// ersten Schritt; stopp gesetzt = der Betreiber hat gestoppt, der Abschluss steht noch aus.
export type ChatLive = { schritt: string; schritt_nr: number; zwischenstand: Dokument | null; stopp: StoppArt | null; denken: string; schritte: SpurSchritt[] };

export type ChatStand = { laeuft: boolean; verlauf: ChatEintrag[]; live: ChatLive | null; neueste: number | null };

// auswahl: die markierten Elemente (Chips) oder - ohne Chips - wie bisher die eine Auswahl im Fenster.
export type ChatKontext = { fenster: string; auswahl: string | AuswahlKontext[] | null; anhaenge?: AnhangKontext[] };

export type Geraet = 'handy' | 'tablet' | 'pc';
export const GERAETE: ReadonlyArray<[Geraet, string]> = [
  ['handy', 'Handy'],
  ['tablet', 'Tablet'],
  ['pc', 'PC'],
];

// Block-id -> Geraet -> Bild (medien:gs-…; Anzeige ueber quelleAnzeige).
export type ExportVorschau = Record<string, Record<Geraet, string>>;

type Fehler = { ok: false; grund: string };
const KEINE_VERBINDUNG = 'Keine Verbindung zum Pult';
const UNVERSTAENDLICH = 'Antwort unverständlich';

function istObjekt(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function nurTexte(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

function zahlOderNull(v: unknown): number | null | undefined {
  if (v === null) return null;
  return typeof v === 'number' && Number.isInteger(v) ? v : undefined;
}

// Schreibender Aufruf mit CSRF (body undefined = ohne Body); liefert das Antwortobjekt oder den
// Grund des Servers.
async function senden(
  s: Start,
  url: string,
  body: unknown,
  sonst: string,
  methode: 'POST' | 'PUT' | 'DELETE' = 'POST',
): Promise<{ ok: true; j: Record<string, unknown> } | Fehler> {
  let r: Response;
  try {
    r = await fetch(url, {
      method: methode,
      credentials: 'same-origin',
      headers: body === undefined ? { 'X-CSRF': s.csrf } : { 'Content-Type': 'application/json', 'X-CSRF': s.csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    return { ok: false, grund: KEINE_VERBINDUNG };
  }
  const roh: unknown = await r.json().catch(() => ({}));
  const j = istObjekt(roh) ? roh : {};
  if (!r.ok) return { ok: false, grund: typeof j.grund === 'string' && j.grund ? j.grund : sonst };
  return { ok: true, j };
}

export async function chatSenden(
  s: Start,
  nachricht: string,
  kontext: ChatKontext,
): Promise<{ ok: true; auftrag: string; status: 'offen' | 'wartet' } | Fehler> {
  const r = await senden(s, s.chat_url, { nachricht, kontext }, 'Der Assistent ist gerade nicht erreichbar');
  if (!r.ok) return r;
  if (typeof r.j.auftrag !== 'string' || !r.j.auftrag) return { ok: false, grund: UNVERSTAENDLICH };
  return { ok: true, auftrag: r.j.auftrag, status: r.j.status === 'wartet' ? 'wartet' : 'offen' };
}

export type Hochladen = {
  promise: Promise<{ ok: true; name: string; art: 'bild' | 'dokument'; groesse: number } | Fehler>;
  abbrechen: () => void;
};

// Anhang fuer den Chat ablegen (multipart "datei", X-CSRF). XHR statt fetch: nur so gibt es den
// Upload-Fortschritt (0..1). Der gespeicherte Name kann vom Dateinamen abweichen - immer den aus
// der Antwort verwenden.
export function anhangHochladen(s: Start, datei: File, fortschritt: (anteil: number) => void): Hochladen {
  if (!s.anhang_url) return { promise: Promise.resolve({ ok: false, grund: 'Anhänge sind hier noch nicht eingerichtet' }), abbrechen: () => undefined };
  const xhr = new XMLHttpRequest();
  const promise = new Promise<Awaited<Hochladen['promise']>>((fertig) => {
    xhr.open('POST', s.anhang_url as string);
    xhr.withCredentials = true;
    xhr.setRequestHeader('X-CSRF', s.csrf);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) fortschritt(Math.min(1, e.loaded / e.total));
    };
    xhr.onerror = () => fertig({ ok: false, grund: KEINE_VERBINDUNG });
    xhr.onabort = () => fertig({ ok: false, grund: 'Abgebrochen' });
    xhr.onload = () => {
      let roh: unknown = null;
      try {
        roh = JSON.parse(xhr.responseText);
      } catch {
        roh = null;
      }
      const j = istObjekt(roh) ? roh : {};
      if (xhr.status < 200 || xhr.status >= 300) {
        const sonst = xhr.status === 413 ? 'Die Datei ist zu groß' : 'Hochladen gerade nicht möglich';
        return fertig({ ok: false, grund: typeof j.grund === 'string' && j.grund ? j.grund : sonst });
      }
      const { name, art, groesse } = j;
      if (typeof name !== 'string' || !name || (art !== 'bild' && art !== 'dokument')) return fertig({ ok: false, grund: UNVERSTAENDLICH });
      fertig({ ok: true, name, art, groesse: typeof groesse === 'number' ? groesse : datei.size });
    };
    const form = new FormData();
    form.append('datei', datei, datei.name);
    xhr.send(form);
  });
  return { promise, abbrechen: () => xhr.abort() };
}

function exportAuswahlLesen(v: unknown): ExportAuswahl | null {
  if (!istObjekt(v) || typeof v.newsletter !== 'boolean' || !Array.isArray(v.flaechen)) return null;
  if (!v.flaechen.every((f) => typeof f === 'string')) return null;
  return { newsletter: v.newsletter, flaechen: v.flaechen as string[] };
}

export function schritteLesen(v: unknown): SpurSchritt[] {
  if (!Array.isArray(v)) return [];
  const aus: SpurSchritt[] = [];
  for (const s of v) {
    if (istObjekt(s) && typeof s.zeit === 'string' && typeof s.text === 'string') aus.push({ zeit: s.zeit, text: s.text });
  }
  return aus.slice(0, 60); // die DB liefert ohnehin hoechstens 60
}

export function denkAusschnitt(text: string, zeichen = 600): string {
  return text.length > zeichen ? '…' + text.slice(-zeichen) : text;
}

const STATUS: ReadonlyArray<ChatStatus> = ['offen', 'in_arbeit', 'wartet', 'fertig', 'fehler'];

// Ein Verlaufseintrag aus der Antwort; null, wenn die Form nicht stimmt.
function eintragLesen(v: unknown): ChatEintrag | null {
  if (!istObjekt(v) || typeof v.id !== 'string' || (v.art !== 'chat' && v.art !== 'export')) return null;
  const status = STATUS.find((st) => st === v.status);
  const vorher = zahlOderNull(v.fassung_vorher ?? null);
  const nachher = zahlOderNull(v.fassung_nachher ?? null);
  if (!status || vorher === undefined || nachher === undefined) return null;
  const roh = istObjekt(v.ergebnis) ? v.ergebnis : {};
  const ergebnis: ChatEintrag['ergebnis'] = {};
  if ('export_vorschlag' in roh) ergebnis.export_vorschlag = exportAuswahlLesen(roh.export_vorschlag);
  if (typeof roh.notiz === 'string') ergebnis.notiz = roh.notiz;
  return {
    id: v.id,
    art: v.art,
    nachricht: typeof v.nachricht === 'string' ? v.nachricht : '',
    antwort: typeof v.antwort === 'string' ? v.antwort : '',
    status,
    hinweise: nurTexte(v.hinweise),
    ergebnis,
    fassung_vorher: vorher,
    fassung_nachher: nachher,
    erstellt_am: typeof v.erstellt_am === 'string' ? v.erstellt_am : '',
    denken: typeof v.denken === 'string' ? v.denken : '',
    schritte: schritteLesen(v.schritte),
    schritt: typeof v.schritt === 'string' ? v.schritt : '',
    schritt_nr: typeof v.schritt_nr === 'number' && Number.isInteger(v.schritt_nr) && v.schritt_nr > 0 ? v.schritt_nr : 0,
    stopp: v.stopp === 'behalten' || v.stopp === 'verwerfen' ? v.stopp : null,
    bild_hinweise: nurTexte(v.bild_hinweise),
  };
}

function liveLesen(v: unknown): ChatLive | null {
  if (!istObjekt(v)) return null;
  const nr = v.schritt_nr;
  return {
    schritt: typeof v.schritt === 'string' ? v.schritt : '',
    schritt_nr: typeof nr === 'number' && Number.isInteger(nr) && nr > 0 ? nr : 0,
    zwischenstand: istObjekt(v.zwischenstand) ? v.zwischenstand : null,
    stopp: v.stopp === 'behalten' || v.stopp === 'verwerfen' ? v.stopp : null,
    denken: typeof v.denken === 'string' ? v.denken : '',
    schritte: schritteLesen(v.schritte),
  };
}

export async function chatLaden(s: Start): Promise<ChatStand | null> {
  try {
    const r = await fetch(s.chat_stand_url, { credentials: 'same-origin' });
    if (!r.ok) return null;
    const j: unknown = await r.json();
    if (!istObjekt(j) || typeof j.laeuft !== 'boolean' || !Array.isArray(j.verlauf)) return null;
    const verlauf = j.verlauf.map(eintragLesen).filter((e): e is ChatEintrag => e !== null);
    return { laeuft: j.laeuft, verlauf, live: liveLesen(j.live), neueste: typeof j.neueste_fassung === 'number' && Number.isInteger(j.neueste_fassung) ? j.neueste_fassung : null };
  } catch {
    return null;
  }
}

// Stopp des laufenden Auftrags. auftrag: nur diesen stoppen (laeuft inzwischen ein anderer,
// passiert nichts - veraltet). abgeschlossen: sofort erledigt (Auftrag hatte noch nicht begonnen).
export async function stoppen(
  s: Start,
  art: StoppArt,
  auftrag?: string,
): Promise<{ ok: true; abgeschlossen: boolean; veraltet: boolean } | Fehler> {
  const body = auftrag === undefined ? { art } : { art, auftrag };
  const r = await senden(s, s.chat_stopp_url, body, 'Stoppen gerade nicht möglich');
  if (!r.ok) return r;
  return { ok: true, abgeschlossen: r.j.abgeschlossen === true, veraltet: r.j.veraltet === true };
}

export async function rueckgaengig(s: Start, auftrag: string): Promise<{ ok: true; fassung: number } | Fehler> {
  const r = await senden(s, s.chat_rueckgaengig_url, { auftrag }, 'Rückgängig gerade nicht möglich');
  if (!r.ok) return r;
  return typeof r.j.fassung === 'number' ? { ok: true, fassung: r.j.fassung } : { ok: false, grund: UNVERSTAENDLICH };
}

export async function exportVorschau(s: Start, flaechen: string[]): Promise<{ ok: true; flaechen: ExportVorschau } | Fehler> {
  const r = await senden(s, s.export_vorschau_url, { flaechen }, 'Vorschau gerade nicht möglich');
  if (!r.ok) return r;
  const roh = istObjekt(r.j.flaechen) ? r.j.flaechen : {};
  const erg: ExportVorschau = {};
  for (const [id, v] of Object.entries(roh)) {
    if (!istObjekt(v)) continue;
    const { handy, tablet, pc } = v;
    if (typeof handy === 'string' && typeof tablet === 'string' && typeof pc === 'string') erg[id] = { handy, tablet, pc };
  }
  return { ok: true, flaechen: erg };
}

export async function exportieren(
  s: Start,
  auswahl: ExportAuswahl,
): Promise<{ ok: true; dateien: string[]; auftrag: string | null } | Fehler> {
  const body = { newsletter: auswahl.newsletter, flaechen: auswahl.flaechen, bestaetigt: true };
  const r = await senden(s, s.export_url, body, 'Export gerade nicht möglich');
  if (!r.ok) return r;
  if (!Array.isArray(r.j.dateien)) return { ok: false, grund: UNVERSTAENDLICH };
  return { ok: true, dateien: nurTexte(r.j.dateien), auftrag: typeof r.j.auftrag === 'string' ? r.j.auftrag : null };
}

const LAEUFT: ReadonlyArray<ChatStatus> = ['offen', 'in_arbeit'];
const RUNDE: ReadonlyArray<ChatStatus> = ['offen', 'in_arbeit', 'wartet'];

// fassung_nachher eines Eintrags, der seit der letzten Abfrage fertig geworden ist (vorher offen/in_arbeit/wartet);
// null, wenn keiner eine neue Fassung gebracht hat.
export function neueFassungNachChat(vorher: ChatEintrag[], nachher: ChatEintrag[]): number | null {
  const lief = new Set(vorher.filter((e) => RUNDE.includes(e.status)).map((e) => e.id));
  let neueste: number | null = null;
  for (const e of nachher) {
    if (e.status !== 'fertig' || e.fassung_nachher === null || !lief.has(e.id)) continue;
    if (neueste === null || e.fassung_nachher > neueste) neueste = e.fassung_nachher;
  }
  return neueste;
}

export function exportVorschlag(e: ChatEintrag): ExportAuswahl | null {
  return exportAuswahlLesen(e.ergebnis.export_vorschlag);
}

// Wie spaces/marketing/api/chat.py slug(): nur fuer die Namensvorschau im Dialog.
export function titelSlug(titel: string): string {
  const s = titel
    .toLowerCase()
    .replace(/ä/g, 'ae')
    .replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue')
    .replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return s.slice(0, 60).replace(/^-+|-+$/g, '') || 'newsletter';
}

export function dateiNamen(slug: string, auswahl: ExportAuswahl): string[] {
  const namen: string[] = [];
  if (auswahl.newsletter) for (const [g] of GERAETE) namen.push(`${slug}-${g}.jpg`);
  for (const f of auswahl.flaechen) for (const [g] of GERAETE) namen.push(`${slug}-${f}-${g}.jpg`);
  return namen;
}

// Rueckgaengig stellt die Fassung VOR dieser Runde wieder her (bei nachgespielten Runden die Fassung, auf die
// nachgespielt wurde). Erlaubt nur an der Runde, deren Fassung die neueste ist - sonst drehte es fremde Arbeit
// zurueck. Liefert deren id oder null.
export function rueckgaengigFuer(verlauf: ChatEintrag[], neueste: number | null): string | null {
  if (neueste === null) return null;
  const e = verlauf.find((x) => x.art === 'chat' && x.status === 'fertig' && x.fassung_nachher === neueste);
  return e ? e.id : null;
}

// Alle Chat-Runden, die laufen oder auf einen Platz warten, in Verlaufsreihenfolge.
export function laufendeRunden(chat: Pick<ChatStand, 'verlauf'> | null): ChatEintrag[] {
  return (chat?.verlauf ?? []).filter((e) => e.art === 'chat' && RUNDE.includes(e.status));
}

export function exportLaeuft(chat: Pick<ChatStand, 'verlauf'> | null): boolean {
  return (chat?.verlauf ?? []).some((e) => e.art === 'export' && LAEUFT.includes(e.status));
}

// Uebergang bis Task 9: die erste laufende Runde (Stopp in der Kopfzeile).
export function laufenderChat(chat: Pick<ChatStand, 'laeuft' | 'verlauf'> | null): ChatEintrag | null {
  if (!chat?.laeuft) return null;
  return laufendeRunden(chat).find((e) => e.status !== 'wartet') ?? null;
}

// Der Stopp-Dialog gilt nur fuer die Runde, fuer die er geoeffnet wurde: endet sie, geht er zu.
export function stoppDialogOffen(stoppFuer: string | null, chat: Pick<ChatStand, 'laeuft' | 'verlauf'> | null): boolean {
  return stoppFuer !== null && laufendeRunden(chat).some((e) => e.id === stoppFuer && e.status !== 'wartet');
}

// Text der Sperre, solange eine Runde laeuft oder wartet (null = frei).
export function sperrText(chat: Pick<ChatStand, 'laeuft' | 'verlauf'> | null): string | null {
  if (!chat?.laeuft) return null;
  return exportLaeuft(chat) ? 'Newsletter-Bilder werden gerechnet …' : 'Agent arbeitet …';
}
