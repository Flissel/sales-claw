// Anbindung des Editors an das Marketing-Pult (sales-claw Spec
// 2026-09-29-newsletter-editor-design.md §3.1). Einzige Stelle mit Netzverkehr:
// nur relative Adressen von sales-ui.
export type Dokument = Record<string, unknown>;

export type Start = {
  dokument: Dokument;
  betreff: string;
  vorschautext: string;
  basis_fassung: number;
  speichern_url: string;
  vorschau_url: string;
  medien_url: string;
  zurueck_url: string;
  csrf: string;
};

export function startLesen(): Start {
  const el = document.getElementById('editor-start');
  if (!el?.textContent) throw new Error('Startdaten fehlen');
  return JSON.parse(el.textContent) as Start;
}

// Im Dokument stehen Bilder als "medien:<name>"; im Editor-Bild zeigen wir
// die angemeldete Medien-Adresse. Beim Speichern zurueck.
export const ANZEIGE = '/medien/datei/';

export function zurAnzeige<T extends Dokument>(doc: T): T {
  return umschreiben(doc, (u) => (u.startsWith('medien:') ? ANZEIGE + encodeURIComponent(u.slice(7)) : u));
}

export function zurSpeicherung<T extends Dokument>(doc: T): T {
  return umschreiben(doc, (u) => (u.startsWith(ANZEIGE) ? 'medien:' + decodeURIComponent(u.slice(ANZEIGE.length)) : u));
}

function istObjekt(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

function umschreiben<T extends Dokument>(doc: T, f: (u: string) => string): T {
  const neu = JSON.parse(JSON.stringify(doc)) as T;
  for (const b of Object.values(neu)) {
    if (!istObjekt(b) || b.type !== 'Image' || !istObjekt(b.data) || !istObjekt(b.data.props)) continue;
    const props = b.data.props;
    if (typeof props.url === 'string') props.url = f(props.url);
  }
  return neu;
}

// Nur Dateien, die die Pruefung in der Datenbank annimmt (medien:<datei>).
const MEDIEN_NAME = /^[A-Za-z0-9._-]{1,120}\.(png|jpe?g|gif|webp)$/i;
export function medienNameOk(name: string): boolean {
  return MEDIEN_NAME.test(name) && !name.includes('..');
}

export type Ergebnis = { ok: true; fassung: number } | { ok: false; konflikt: boolean; grund: string };

export async function speichern(
  s: Start,
  doc: Dokument,
  betreff: string,
  vorschautext: string,
  basis: number,
  alsKopie: boolean
): Promise<Ergebnis> {
  let r: Response;
  try {
    r = await fetch(s.speichern_url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': s.csrf },
      body: JSON.stringify({
        basis_fassung: basis,
        betreff,
        vorschautext,
        dokument: zurSpeicherung(doc),
        als_kopie: alsKopie,
      }),
    });
  } catch {
    return { ok: false, konflikt: false, grund: 'Keine Verbindung zum Pult – Änderungen sind noch da.' };
  }
  const j: unknown = await r.json().catch(() => ({}));
  const antwort = istObjekt(j) ? j : {};
  if (r.ok && typeof antwort.fassung === 'number') return { ok: true, fassung: antwort.fassung };
  const grund = typeof antwort.grund === 'string' && antwort.grund ? antwort.grund : 'Speichern gerade nicht möglich';
  return { ok: false, konflikt: r.status === 409, grund };
}

export async function medienListe(s: Start): Promise<string[]> {
  try {
    const r = await fetch(s.medien_url, { credentials: 'same-origin' });
    if (!r.ok) return [];
    const j: unknown = await r.json();
    if (!istObjekt(j) || !Array.isArray(j.bilder)) return [];
    return j.bilder.filter((b): b is string => typeof b === 'string' && medienNameOk(b));
  } catch {
    return [];
  }
}
