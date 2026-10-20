// Assistent im Collage-Editor (Freie Fläche Stufe 3): Speichern vor dem Senden. Der Assistent arbeitet mit
// der gespeicherten Fassung - Ungespeichertes geht vorher mit seiteSpeichern als neue Fassung. Bei Konflikt
// kommt der Konfliktdialog des Editors, und es wird nichts gesendet.
import type { ChatKontext } from './chat';
import { seitenChip } from './chatKontext';
import { fehlerText, type Start } from './pult';
import { pultStore } from './pultZustand';
import { speicherGrund, type Seite, type SeitenEbene } from './seite';
import { seiteSpeichern } from './seitePult';

export const SEITE_KONFLIKT = 'Inzwischen gibt es eine neuere Fassung – erst neu laden oder als Kopie behalten';

export type SeitenStand = { seite: Seite; betreff: string; vorschautext: string; basis: number; ungespeichert: boolean };
export type SeitenFolgen = { gespeichert: (fassung: number) => void; konflikt: () => void };

// Fuer editorEinstecken: holen liefert den Stand im Moment des Sendens. Liefert null oder den Grund.
export function seitenSicherung(start: Start, holen: () => SeitenStand, folgen: SeitenFolgen): () => Promise<string | null> {
  return async () => {
    const st = holen();
    if (!st.ungespeichert) return null;
    const grund = speicherGrund(st.seite);
    if (grund) return fehlerText(grund);
    const r = await seiteSpeichern(start, st.seite, st.betreff, st.vorschautext, st.basis, false);
    if (r.ok) {
      // Sofort, nicht erst nach dem naechsten Rendern: die Runde merkt sich fassung_vorher. "ungespeichert"
      // gleicht der Editor selbst ab (es koennte waehrend des Speicherns schon wieder etwas geaendert sein).
      pultStore.setState({ basis: r.fassung });
      folgen.gespeichert(r.fassung);
      return null;
    }
    if ('konflikt' in r) {
      folgen.konflikt();
      return SEITE_KONFLIKT;
    }
    return fehlerText(r.grund);
  };
}

// Kontext der Nachricht: die gewaehlte Ebene geht von selbst mit, als Listeneintrag {art: 'ebene', id, kurz}
// (der Collage-Arbeiter liest nur die Liste, nie die Einzelform). Angehaengte Chips ersetzen sie (mitChips).
export function seitenKontext(ebene: SeitenEbene | null): ChatKontext {
  if (!ebene) return { fenster: 'seite', auswahl: null };
  const { art, id, kurz } = seitenChip(ebene);
  return { fenster: 'seite', auswahl: [{ art, id, kurz }] };
}
