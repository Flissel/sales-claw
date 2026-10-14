// Gemeinsamer Ablauf jeder Schreibanfrage (Ziehen, Fenster, Loeschen):
// Konflikt -> fragen -> ggf. mit trotzdem wiederholen; veraltet -> neu laden;
// Erfolg -> Entwurfs-/Hinweis-Meldung und neu laden.
import type { Ergebnis } from './api';

export const VERALTET = 'inzwischen geändert – neu laden';
export const ENTWURF_ANGELEGT = 'Entwurf an Kunde angelegt – in Freigaben';
export const UNVOLLSTAENDIG = 'unvollständig geprüft';

export interface Konflikt {
  art: string;
  titel: string;
  beginn: string;
  ende: string;
}

export interface Oberflaeche {
  konfliktFragen(konflikte: Konflikt[], unvollstaendig: boolean): Promise<boolean>;
  melden(text: string, link?: string): void;
  neuLaden(): void;
}

/** -> true, wenn der Server die Aenderung angenommen hat. */
export async function schreiben(
  anfrage: (trotzdem: boolean) => Promise<Ergebnis>,
  ui: Oberflaeche,
  freigabenUrl: string,
): Promise<boolean> {
  let r = await anfrage(false);
  if (r.status === 409 && r.daten.grund === 'Konflikt') {
    const konflikte = Array.isArray(r.daten.konflikte) ? (r.daten.konflikte as Konflikt[]) : [];
    if (!(await ui.konfliktFragen(konflikte, r.daten.unvollstaendig === true))) return false;
    r = await anfrage(true);
  }
  if (r.status === 409 && r.daten.grund === VERALTET) {
    ui.melden(VERALTET);
    ui.neuLaden();
    return false;
  }
  if (!r.ok) {
    ui.melden(r.daten.grund ?? 'Speichern fehlgeschlagen');
    // 503 kann heissen: geaendert, nur der Kunde ist nicht benachrichtigt -> Stand neu holen.
    if (r.status === 503) ui.neuLaden();
    // Traegt die 503 das Ergebnis (ereignis/geloescht), ist die Aenderung gespeichert:
    // Fenster schliessen, nicht zuruecksetzen - sonst folgt beim zweiten Speichern VERALTET.
    return r.status === 503 && (r.daten.ereignis !== undefined || r.daten.geloescht === true);
  }
  if (r.daten.entwurf) ui.melden(ENTWURF_ANGELEGT, freigabenUrl);
  if (typeof r.daten.hinweis === 'string' && r.daten.hinweis) ui.melden(r.daten.hinweis);
  ui.neuLaden();
  return true;
}
