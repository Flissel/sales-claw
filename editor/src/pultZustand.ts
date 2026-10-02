import { create } from 'zustand';

import { ladeEntscheid, neuesBildMeldung } from './bildfeld';
import type { Auftrag } from './bildfeld';
import { ChatKontext, chatLaden, chatSenden, ChatStand, neueFassungNachChat, rueckgaengig } from './chat';
import { getDocument, setDocument, setSelectedBlockId } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import { Ergebnis, fehlerText, medienListe, speichern, standLaden, Start } from './pult';

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
  // Meldet das offene Fenster: ungesicherte Aenderungen an der Flaeche, ausgewaehlte Ebene.
  gestaltungGeaendert: boolean;
  gestaltungAuswahl: string | null;
  // Chat mit dem Gestaltungs-Agenten (null = noch nicht geladen). laeuft sperrt das Dokument.
  chat: ChatStand | null;
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
  gestaltungGeaendert: false,
  gestaltungAuswahl: null,
  chat: null,
}));

export function gestaltungOeffnen(id: string) {
  pultStore.setState({ gestaltungOffen: id });
}

export function gestaltungSchliessen() {
  pultStore.setState({ gestaltungOffen: null, gestaltungGeaendert: false, gestaltungAuswahl: null });
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
const FENSTER = 'vibemind-fenster';

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

// Gibt es eine neuere Fassung als die geladene und nichts Ungesichertes, laedt die Seite neu
// (Bildauftraege ueber standAbfragen, Agenten-Antworten und Rueckgaengig ueber den Chat).
// Schutz gegen Neuladeschleifen: je Fassung hoechstens einmal automatisch (sessionStorage).
// Ein offenes, unveraendertes Gestaltungsfenster geht dabei nicht verloren - es oeffnet sich wieder.
export function neueFassungLaden(fassung: number, auftraege: Auftrag[] = []) {
  const { basis, ungespeichert, hinweisOffen, geladenUm, gestaltungOffen, gestaltungGeaendert } = pultStore.getState();
  const offen = ungespeichert || hinweisOffen || (gestaltungOffen !== null && gestaltungGeaendert);
  if (ladeEntscheid(fassung, basis, offen, schonGeladenLesen()) !== 'laden') return;
  const m = neuesBildMeldung(auftraege, geladenUm);
  try {
    sessionStorage.setItem(NEU_GELADEN, String(fassung));
    if (m) sessionStorage.setItem(MERKZETTEL, JSON.stringify(m));
    if (gestaltungOffen !== null) sessionStorage.setItem(FENSTER, gestaltungOffen);
  } catch {
    /* ohne Merkzettel wird nur neu geladen */
  }
  window.location.reload();
}

// Nach dem Neuladen: war ein Gestaltungsfenster offen, oeffnet es sich wieder.
export function fensterWiederOeffnen() {
  try {
    const id = sessionStorage.getItem(FENSTER);
    if (id === null) return;
    sessionStorage.removeItem(FENSTER);
    if (getDocument()[id]?.type === 'Image') gestaltungOeffnen(id);
  } catch {
    /* kein Merkzettel */
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
    neueFassungLaden(s.fassung, s.auftraege);
  };
  void holen();
  if (!standTakt) standTakt = setInterval(holen, 15000);
}

// Chat-Stand: einmal beim Laden, danach alle 2 s, solange der Agent arbeitet.
// Jeder Aufruf beginnt eine neue Runde; aeltere Runden planen nichts mehr ein.
export const CHAT_TAKT_MS = 2000;
let chatRunde = 0;
let chatTakt: ReturnType<typeof setTimeout> | null = null;
export function chatAbfragen() {
  const runde = ++chatRunde;
  if (chatTakt) clearTimeout(chatTakt);
  chatTakt = null;
  const holen = async () => {
    const { start } = pultStore.getState();
    if (!start) return;
    const neu = await chatLaden(start);
    if (runde !== chatRunde) return;
    if (neu) {
      const vorher = pultStore.getState().chat?.verlauf ?? [];
      pultStore.setState({ chat: neu });
      const f = neueFassungNachChat(vorher, neu.verlauf);
      if (f !== null) neueFassungLaden(f);
    }
    // Netzfehler waehrend der Agent arbeitet: weiter fragen, die Sperre bleibt sichtbar.
    if (pultStore.getState().chat?.laeuft) chatTakt = setTimeout(holen, CHAT_TAKT_MS);
  };
  void holen();
}

export const HINWEIS_OFFEN = 'Im Bildfeld steht noch ein Hinweis – erst beauftragen oder leeren';

// Nachricht an den Agenten. Ungesicherte Aenderungen am Newsletter werden vorher gespeichert -
// der Agent arbeitet mit der gespeicherten Fassung. Liefert null oder den Grund fuer den Betreiber.
export async function chatAbschicken(nachricht: string, kontext: ChatKontext): Promise<string | null> {
  const { start, ungespeichert, hinweisOffen, chat } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  if (chat?.laeuft) return 'Der Assistent arbeitet gerade';
  // Wie beim Neuladen: ein offener Bildhinweis hielte es auf - die Agenten-Fassung bliebe ungeladen.
  if (hinweisOffen) return HINWEIS_OFFEN;
  if (ungespeichert) {
    const e = await newsletterSichern(false);
    if (!e.ok) return fehlerText(e.grund);
  }
  const r = await chatSenden(start, nachricht, kontext);
  if (!r.ok) {
    // Z. B. arbeitet der Assistent schon fuer einen anderen Tab: Stand holen, damit die Sperre erscheint.
    chatAbfragen();
    return r.grund;
  }
  // Vorlaeufiger Eintrag: sperrt sofort und laesst neueFassungNachChat den Uebergang erkennen.
  const eintrag = {
    id: r.auftrag,
    art: 'chat' as const,
    nachricht,
    antwort: '',
    status: 'offen' as const,
    hinweise: [],
    ergebnis: {},
    fassung_vorher: pultStore.getState().basis,
    fassung_nachher: null,
    erstellt_am: new Date().toISOString(),
  };
  const verlauf = (pultStore.getState().chat?.verlauf ?? []).filter((e) => e.id !== r.auftrag);
  pultStore.setState({ chat: { laeuft: true, verlauf: [...verlauf, eintrag] } });
  chatAbfragen();
  return null;
}

// Rueckgaengig legt die Fassung vor der Agenten-Antwort als neue Fassung an; danach neu laden.
export async function chatRueckgaengig(auftrag: string): Promise<string | null> {
  const { start, ungespeichert, hinweisOffen, chat } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  if (chat?.laeuft) return 'Der Assistent arbeitet gerade';
  if (hinweisOffen) return HINWEIS_OFFEN;
  if (ungespeichert) return 'Erst speichern – sonst gingen deine Änderungen verloren';
  const r = await rueckgaengig(start, auftrag);
  if (!r.ok) return r.grund;
  neueFassungLaden(r.fassung);
  return null;
}
