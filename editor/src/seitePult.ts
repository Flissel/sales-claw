// Speichern einer Collage (Freie Fläche Stufe 2): POST an start.speichern_url (…/seite),
// Muster wie pult.ts speichern. Bilder bleiben "medien:<datei>", hier wird nichts umgeschrieben.
import type { Start } from './pult';
import type { Seite } from './seite';

export type SeiteErgebnis = { ok: true; fassung: number } | { ok: false; konflikt: true } | { ok: false; grund: string };

function istObjekt(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export async function seiteSpeichern(
  start: Start,
  seite: Seite,
  betreff: string,
  vorschautext: string,
  basis: number,
  alsKopie: boolean
): Promise<SeiteErgebnis> {
  let r: Response;
  try {
    r = await fetch(start.speichern_url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': start.csrf },
      body: JSON.stringify({ basis_fassung: basis, seite, betreff, vorschautext, als_kopie: alsKopie }),
    });
  } catch {
    return { ok: false, grund: 'Keine Verbindung zum Pult' };
  }
  const j: unknown = await r.json().catch(() => ({}));
  const antwort = istObjekt(j) ? j : {};
  if (r.ok && typeof antwort.fassung === 'number') return { ok: true, fassung: antwort.fassung };
  if (r.status === 409) return { ok: false, konflikt: true };
  const grund = typeof antwort.grund === 'string' && antwort.grund ? antwort.grund : 'Speichern gerade nicht möglich';
  return { ok: false, grund };
}
