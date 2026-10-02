// Anbindung an den Gestaltungs-Agenten und den Export (Spec 2026-10-02 §4, §6):
// Chat senden/lesen, Rueckgaengig, Export-Vorschau und bestaetigter Export.
// Nur relative Adressen aus den Startdaten; schreibende Aufrufe mit X-CSRF.
import type { Start } from './pult';

export type ExportAuswahl = { newsletter: boolean; flaechen: string[] };

export type ChatStatus = 'offen' | 'in_arbeit' | 'fertig' | 'fehler';

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
};

export type ChatStand = { laeuft: boolean; verlauf: ChatEintrag[] };

export type ChatKontext = { fenster: string; auswahl: string | null };

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

// POST mit CSRF; liefert das Antwortobjekt oder den Grund des Servers.
async function senden(
  s: Start,
  url: string,
  body: unknown,
  sonst: string,
): Promise<{ ok: true; j: Record<string, unknown> } | Fehler> {
  let r: Response;
  try {
    r = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': s.csrf },
      body: JSON.stringify(body),
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
): Promise<{ ok: true; auftrag: string } | Fehler> {
  const r = await senden(s, s.chat_url, { nachricht, kontext }, 'Der Assistent ist gerade nicht erreichbar');
  if (!r.ok) return r;
  return typeof r.j.auftrag === 'string' && r.j.auftrag ? { ok: true, auftrag: r.j.auftrag } : { ok: false, grund: UNVERSTAENDLICH };
}

function exportAuswahlLesen(v: unknown): ExportAuswahl | null {
  if (!istObjekt(v) || typeof v.newsletter !== 'boolean' || !Array.isArray(v.flaechen)) return null;
  if (!v.flaechen.every((f) => typeof f === 'string')) return null;
  return { newsletter: v.newsletter, flaechen: v.flaechen as string[] };
}

const STATUS: ReadonlyArray<ChatStatus> = ['offen', 'in_arbeit', 'fertig', 'fehler'];

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
  };
}

export async function chatLaden(s: Start): Promise<ChatStand | null> {
  try {
    const r = await fetch(s.chat_stand_url, { credentials: 'same-origin' });
    if (!r.ok) return null;
    const j: unknown = await r.json();
    if (!istObjekt(j) || typeof j.laeuft !== 'boolean' || !Array.isArray(j.verlauf)) return null;
    const verlauf = j.verlauf.map(eintragLesen).filter((e): e is ChatEintrag => e !== null);
    return { laeuft: j.laeuft, verlauf };
  } catch {
    return null;
  }
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

// fassung_nachher eines Eintrags, der seit der letzten Abfrage fertig geworden ist
// (vorher offen/in_arbeit); null, wenn keiner eine neue Fassung gebracht hat.
export function neueFassungNachChat(vorher: ChatEintrag[], nachher: ChatEintrag[]): number | null {
  const lief = new Set(vorher.filter((e) => LAEUFT.includes(e.status)).map((e) => e.id));
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

// Rueckgaengig stellt die Fassung VOR dieser Antwort wieder her - bei einer aelteren Antwort
// verschwaende damit alles Spaetere. Erlaubt also nur fuer die neueste fertige Chat-Antwort mit
// Fassung, und nur solange deren Fassung die aktuelle ist. Liefert deren id oder null.
export function rueckgaengigFuer(verlauf: ChatEintrag[], basis: number): string | null {
  for (let i = verlauf.length - 1; i >= 0; i--) {
    const e = verlauf[i];
    if (e.art !== 'chat' || e.status !== 'fertig' || e.fassung_nachher === null) continue;
    return e.fassung_nachher === basis ? e.id : null;
  }
  return null;
}

// Text der Sperre, solange ein Auftrag offen ist (null = frei).
export function sperrText(chat: ChatStand | null): string | null {
  if (!chat?.laeuft) return null;
  const exportLaeuft = chat.verlauf.some((e) => e.art === 'export' && LAEUFT.includes(e.status));
  return exportLaeuft ? 'Newsletter-Bilder werden gerechnet …' : 'Agent arbeitet …';
}
