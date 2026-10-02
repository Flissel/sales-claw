import { create } from 'zustand';

import { ladeEntscheid, neuesBildMeldung } from './bildfeld';
import type { Auftrag } from './bildfeld';
import { getDocument, setDocument, setSelectedBlockId } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import { Ergebnis, medienListe, speichern, standLaden, Start } from './pult';

// Zustand der Pult-Leiste: Startdaten, Betreff/Vorschautext, gemerkte Fassung
// und ob seit dem letzten Speichern etwas geaendert wurde.
type TPult = {
  start: Start | null;
  betreff: string;
  vorschautext: string;
  basis: number;
  ungespeichert: boolean;
  medien: string[] | null;
  stand: { fassung: number; auftraege: Auftrag[] } | null;
  meldung: { platz: string; text: string } | null;
  // Ladezeitpunkt der Seite (ms) und: steht im Hinweisfeld des Bildpanels etwas (zaehlt wie ungespeichert).
  geladenUm: number;
  hinweisOffen: boolean;
  // Block-id der Gestaltungsflaeche, deren Fenster offen ist (null = Newsletter).
  gestaltungOffen: string | null;
};

export const pultStore = create<TPult>(() => ({
  start: null,
  betreff: '',
  vorschautext: '',
  basis: 0,
  ungespeichert: false,
  medien: null,
  stand: null,
  meldung: null,
  geladenUm: Date.now(),
  hinweisOffen: false,
  gestaltungOffen: null,
}));

export function gestaltungOeffnen(id: string) {
  pultStore.setState({ gestaltungOffen: id });
}

export function gestaltungSchliessen() {
  pultStore.setState({ gestaltungOffen: null });
}

export function pultStarten(start: Start) {
  pultStore.setState({
    start,
    betreff: start.betreff ?? '',
    vorschautext: start.vorschautext ?? '',
    basis: start.basis_fassung,
    ungespeichert: false,
    geladenUm: Date.now(),
  });
}

export function alsUngespeichert() {
  if (!pultStore.getState().ungespeichert) pultStore.setState({ ungespeichert: true });
}

// Newsletter als neue Fassung speichern (Pult-Leiste und Gestaltungsfenster).
// aenderung: wird auf das Dokument angewandt und nur bei Erfolg uebernommen - schlaegt das
// Speichern fehl, bleibt das Dokument im Editor, wie es war.
export async function newsletterSichern(
  alsKopie: boolean,
  aenderung?: (d: TEditorConfiguration) => TEditorConfiguration
): Promise<Ergebnis> {
  const { start, betreff: b, vorschautext: v, basis: n } = pultStore.getState();
  if (!start) return { ok: false, konflikt: false, grund: 'Keine Verbindung zum Pult' };
  const vorher = getDocument();
  const zuSichern = aenderung ? aenderung(vorher) : vorher;
  const e = await speichern(start, zuSichern, b, v, n, alsKopie);
  if (e.ok) {
    const nachher = pultStore.getState();
    // Nur als gespeichert markieren, wenn waehrend des Speicherns nichts geaendert wurde.
    const unveraendert = getDocument() === vorher && nachher.betreff === b && nachher.vorschautext === v;
    if (aenderung) setDocument(unveraendert ? zuSichern : aenderung(getDocument()));
    pultStore.setState({ basis: e.fassung, ungespeichert: !unveraendert });
  }
  return e;
}

let medienLaeuft: Promise<void> | null = null;
export function medienLaden(neu = false) {
  const { start } = pultStore.getState();
  if (!start) return;
  if (medienLaeuft && !neu) return;
  medienLaeuft = medienListe(start).then((medien) => pultStore.setState({ medien }));
}

const MERKZETTEL = 'vibemind-neues-bild';
const NEU_GELADEN = 'vibemind-neu-geladen';

function schonGeladenLesen(): number | null {
  try {
    const roh = sessionStorage.getItem(NEU_GELADEN);
    const n = roh === null ? NaN : Number(roh);
    return Number.isInteger(n) ? n : null;
  } catch {
    return null;
  }
}

// Nach dem automatischen Neuladen: Merkzettel lesen und loeschen, Meldung zeigen, Platz hervorheben.
export function meldungLesen() {
  try {
    const roh = sessionStorage.getItem(MERKZETTEL);
    if (roh === null) return;
    sessionStorage.removeItem(MERKZETTEL);
    const j: unknown = JSON.parse(roh);
    if (typeof j !== 'object' || j === null) return;
    const { platz, text } = j as { platz?: unknown; text?: unknown };
    if (typeof platz !== 'string' || typeof text !== 'string') return;
    pultStore.setState({ meldung: { platz, text } });
    if (platz in getDocument()) setSelectedBlockId(platz);
  } catch {
    /* kein Merkzettel, keine Meldung */
  }
}

let standTakt: ReturnType<typeof setInterval> | null = null;
export function standAbfragen() {
  const holen = async () => {
    const { start } = pultStore.getState();
    if (!start) return;
    const s = await standLaden(start);
    if (!s) return;
    pultStore.setState({ stand: s });
    const { basis, ungespeichert, hinweisOffen, geladenUm, gestaltungOffen } = pultStore.getState();
    // Ein offenes Gestaltungsfenster zaehlt wie ungespeichert: Neuladen wuerfe die Flaeche weg.
    const offen = ungespeichert || hinweisOffen || gestaltungOffen !== null;
    if (ladeEntscheid(s.fassung, basis, offen, schonGeladenLesen()) === 'laden') {
      const m = neuesBildMeldung(s.auftraege, geladenUm);
      try {
        sessionStorage.setItem(NEU_GELADEN, String(s.fassung));
        if (m) sessionStorage.setItem(MERKZETTEL, JSON.stringify(m));
      } catch {
        /* ohne Merkzettel wird nur neu geladen */
      }
      window.location.reload();
    }
  };
  void holen();
  if (!standTakt) standTakt = setInterval(holen, 15000);
}

