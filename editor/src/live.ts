// Reine Hilfen fuer die Live-Ansicht des Agenten (Spec 2026-10-02-newsletter-agent-live §2.3):
// welche Bloecke sich zwischen zwei Zwischenstaenden geaendert haben, welcher davon leuchtet,
// der Text der Schritt-Zeile und ob sich ein Zwischenstand gefahrlos im Canvas zeigen laesst.
import type { ChatLive } from './chat';
import { Dokument, kinderVon } from './pult';

function istObjekt(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

// Inhaltlich gleich (Schluesselreihenfolge egal - die Datenbank ordnet jsonb-Schluessel um).
export function gleich(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!istObjekt(a) || !istObjekt(b) || Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => gleich(x, b[i]));
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && gleich(a[k], b[k]));
}

// Block-ids von root aus in Dokumentreihenfolge (vor den Kindern der Block selbst).
function reihenfolge(doc: Dokument): string[] {
  const ids: string[] = [];
  const gesehen = new Set<string>();
  const besuchen = (id: string) => {
    if (gesehen.has(id) || !(id in doc)) return;
    gesehen.add(id);
    ids.push(id);
    for (const k of kinderVon(doc[id])) besuchen(k);
  };
  besuchen('root');
  return ids;
}

// Bloecke in nachher, die neu sind oder sich inhaltlich geaendert haben, in Dokumentreihenfolge.
// Geloeschte und unerreichbare Bloecke zaehlen nicht.
export function geaenderteBloecke(vorher: Dokument, nachher: Dokument): string[] {
  return reihenfolge(nachher).filter((id) => !(id in vorher) || !gleich(vorher[id], nachher[id]));
}

// Der Block, der aufleuchten soll: der letzte geaenderte in Dokumentreihenfolge. root (nur Farben/
// Kinderliste) leuchtet nie, und ein Behaelter tritt hinter ein geaendertes Kind zurueck (er hat
// sich meist nur geaendert, weil das Kind hinzukam).
export function zuletztGeaendert(vorher: Dokument, nachher: Dokument): string | null {
  const ids = geaenderteBloecke(vorher, nachher).filter((id) => id !== 'root');
  const blaetter = ids.filter((id) => !kinderVon(nachher[id]).some((k) => ids.includes(k)));
  return blaetter.length > 0 ? blaetter[blaetter.length - 1] : null;
}

// „Schritt 3 · Titel links oben setzen“; null vor dem ersten Schritt.
export function schrittText(live: ChatLive | null): string | null {
  if (!live || live.schritt_nr <= 0) return null;
  const t = live.schritt.trim();
  return t ? `Schritt ${live.schritt_nr} · ${t}` : `Schritt ${live.schritt_nr}`;
}

const BLOCK_TYPEN = new Set(['EmailLayout', 'Button', 'Container', 'ColumnsContainer', 'Heading', 'Image', 'Text', 'Spacer', 'Divider']);

// Der Zwischenstand ist nicht vom Validator geprueft. Der Canvas stuerzt bei einem fehlenden
// Kind oder einem unbekannten Typ ab - solche Staende zeigen wir nicht.
export function anzeigbar(doc: Dokument): boolean {
  const root = doc.root;
  if (!istObjekt(root) || root.type !== 'EmailLayout') return false;
  const ids = reihenfolge(doc);
  for (const id of ids) {
    const b = doc[id];
    if (!istObjekt(b) || typeof b.type !== 'string' || !BLOCK_TYPEN.has(b.type) || !istObjekt(b.data)) return false;
    if (kinderVon(b).some((k) => !(k in doc))) return false;
  }
  return true;
}
