import { create } from 'zustand';

import { ladeEntscheid, neuesBildMeldung } from './bildfeld';
import type { Auftrag } from './bildfeld';
import {
  ChatEintrag,
  ChatKontext,
  chatLaden,
  chatSenden,
  ChatStand,
  laufenderChat,
  neueFassungNachChat,
  rueckgaengig,
  stoppen,
  StoppArt,
  vormerken,
  vormerkungLoeschen,
  vormerkungStarten,
} from './chat';
import { getDocument, resetDocument, setDocument, setSelectedBlockId } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import { anzeigbar, zuletztGeaendert } from './live';
import { Dokument, Ergebnis, fehlerText, medienListe, speichern, standLaden, Start, zurAnzeige } from './pult';

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
  // Letzte Chat-Abfrage gescheitert, waehrend der Agent arbeitet ("Verbindung …").
  chatGetrennt: boolean;
  // Der Canvas zeigt einen Zwischenstand des Agenten (nur Anzeige, nie gespeichert):
  // echt = das Dokument davor (kommt zurueck, wenn der Lauf ohne neue Fassung endet),
  // stand = der gezeigte Zwischenstand im gespeicherten Format, leuchtet = zuletzt geaenderter
  // Block, puls = zaehlt jeden neuen Stand (startet das Aufleuchten neu).
  zwischenstand: { echt: TEditorConfiguration; stand: Dokument; leuchtet: string | null; puls: number } | null;
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
  chatGetrennt: false,
  zwischenstand: null,
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

// Ein angezeigter Zwischenstand (und das Zurueckholen des echten Dokuments) ist keine Aenderung.
export function alsUngespeichert() {
  const { ungespeichert, zwischenstand } = pultStore.getState();
  if (!ungespeichert && zwischenstand === null) pultStore.setState({ ungespeichert: true });
}

// Newsletter als neue Fassung speichern (Pult-Leiste und Gestaltungsfenster).
// aenderung: wird auf das Dokument angewandt und nur bei Erfolg uebernommen - schlaegt das
// Speichern fehl, bleibt das Dokument im Editor, wie es war.
export async function newsletterSichern(
  alsKopie: boolean,
  aenderung?: (d: TEditorConfiguration) => TEditorConfiguration
): Promise<Ergebnis> {
  const { start, betreff: b, vorschautext: v, basis: n, zwischenstand } = pultStore.getState();
  if (!start) return { ok: false, konflikt: false, grund: 'Keine Verbindung zum Pult' };
  // Im Canvas steht ein Zwischenstand des Agenten - der wird nie gespeichert.
  if (zwischenstand) return { ok: false, konflikt: false, grund: 'Der Assistent arbeitet gerade' };
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
// Liefert true, wenn die Seite neu laedt.
export function neueFassungLaden(fassung: number, auftraege: Auftrag[] = []): boolean {
  const { basis, ungespeichert, hinweisOffen, geladenUm, gestaltungOffen, gestaltungGeaendert } = pultStore.getState();
  const offen = ungespeichert || hinweisOffen || (gestaltungOffen !== null && gestaltungGeaendert);
  if (ladeEntscheid(fassung, basis, offen, schonGeladenLesen()) !== 'laden') return false;
  const m = neuesBildMeldung(auftraege, geladenUm);
  try {
    sessionStorage.setItem(NEU_GELADEN, String(fassung));
    if (m) sessionStorage.setItem(MERKZETTEL, JSON.stringify(m));
    if (gestaltungOffen !== null) sessionStorage.setItem(FENSTER, gestaltungOffen);
  } catch {
    /* ohne Merkzettel wird nur neu geladen */
  }
  window.location.reload();
  return true;
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

// Zwischenstand des Agenten im Canvas zeigen - nur Anzeige: das echte Dokument liegt beiseite,
// alsUngespeichert und newsletterSichern sehen den Zwischenstand und tun nichts.
function zwischenstandZeigen(stand: Dokument) {
  const z = pultStore.getState().zwischenstand;
  if (z && JSON.stringify(z.stand) === JSON.stringify(stand)) return;
  if (!anzeigbar(stand)) return;
  const anzeige = zurAnzeige(stand) as TEditorConfiguration;
  const vorher = getDocument();
  pultStore.setState({
    zwischenstand: { echt: z?.echt ?? vorher, stand, leuchtet: zuletztGeaendert(vorher, anzeige), puls: (z?.puls ?? 0) + 1 },
  });
  resetDocument(anzeige);
}

// Lauf ohne (geladene) neue Fassung zu Ende: das echte Dokument kommt zurueck, wie es war.
function zwischenstandBeenden() {
  const z = pultStore.getState().zwischenstand;
  if (!z) return;
  resetDocument(z.echt);
  pultStore.setState({ zwischenstand: null });
}

// Chat-Stand: einmal beim Laden, danach jede Sekunde, solange ein Chat-Auftrag laeuft
// (Live-Ansicht); ein Newsletter-Export wie bisher alle 2 s.
// Jeder Aufruf beginnt eine neue Runde; aeltere Runden planen nichts mehr ein.
export const CHAT_TAKT_MS = 1000;
export const EXPORT_TAKT_MS = 2000;
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
      pultStore.setState({ chat: neu, chatGetrennt: false });
      // Erst die neue Fassung (auch wenn schon die vorgemerkte Nachricht laeuft) - die Seite laedt neu.
      const f = neueFassungNachChat(vorher, neu.verlauf);
      const laedt = f !== null && neueFassungLaden(f);
      if (!laedt) {
        if (neu.live?.zwischenstand) zwischenstandZeigen(neu.live.zwischenstand);
        else if (!neu.live) zwischenstandBeenden();
      }
    } else if (pultStore.getState().chat?.laeuft) {
      pultStore.setState({ chatGetrennt: true });
    }
    // Netzfehler waehrend der Agent arbeitet: weiter fragen, die Sperre bleibt sichtbar.
    const jetzt = pultStore.getState().chat;
    if (jetzt?.laeuft) chatTakt = setTimeout(holen, laufenderChat(jetzt) ? CHAT_TAKT_MS : EXPORT_TAKT_MS);
  };
  void holen();
}

// Vorlaeufiger Eintrag fuer einen eben gestarteten Auftrag: sperrt sofort und laesst
// neueFassungNachChat den Uebergang erkennen; danach wird abgefragt.
function auftragEintragen(id: string, nachricht: string, rest: Partial<ChatStand> = {}) {
  const eintrag: ChatEintrag = {
    id,
    art: 'chat',
    nachricht,
    antwort: '',
    status: 'offen',
    hinweise: [],
    ergebnis: {},
    fassung_vorher: pultStore.getState().basis,
    fassung_nachher: null,
    erstellt_am: new Date().toISOString(),
  };
  const alt = pultStore.getState().chat;
  const verlauf = (alt?.verlauf ?? []).filter((e) => e.id !== id);
  pultStore.setState({ chat: { live: null, vorgemerkt: null, ...alt, ...rest, laeuft: true, verlauf: [...verlauf, eintrag] } });
  chatAbfragen();
}

export const HINWEIS_OFFEN = 'Im Bildfeld steht noch ein Hinweis – erst beauftragen oder leeren';

// Nachricht an den Agenten. Ungesicherte Aenderungen am Newsletter werden vorher gespeichert -
// der Agent arbeitet mit der gespeicherten Fassung. Liefert null oder den Grund fuer den Betreiber.
export async function chatAbschicken(nachricht: string, kontext: ChatKontext): Promise<string | null> {
  const { start, chat } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  if (chat?.laeuft) return 'Der Assistent arbeitet gerade';
  const grund = await vorDemStart();
  if (grund) return grund;
  // Steht noch eine Vormerkung (nach Fehler/Stopp), uebernimmt PUT sie und startet sie mit dem
  // neuen Text. Ein POST legte einen zweiten Auftrag an, und die alte Vormerkung liefe danach mit.
  if (pultStore.getState().chat?.vorgemerkt) return vormerkungSetzen(start, nachricht, kontext);
  const r = await chatSenden(start, nachricht, kontext);
  if (!r.ok) {
    // Z. B. arbeitet der Assistent schon fuer einen anderen Tab: Stand holen, damit die Sperre erscheint.
    chatAbfragen();
    return r.grund;
  }
  auftragEintragen(r.auftrag, nachricht);
  return null;
}

// Vor jedem Start eines Auftrags: ein offener Bildhinweis hielte das Neuladen auf (die
// Agenten-Fassung bliebe ungeladen); Ungesichertes wird gespeichert - der Agent arbeitet mit
// der gespeicherten Fassung. Liefert null oder den Grund fuer den Betreiber.
async function vorDemStart(): Promise<string | null> {
  const { ungespeichert, hinweisOffen } = pultStore.getState();
  if (hinweisOffen) return HINWEIS_OFFEN;
  if (ungespeichert) {
    const e = await newsletterSichern(false);
    if (!e.ok) return fehlerText(e.grund);
  }
  return null;
}

// Waehrend eines Chat-Laufs: die naechste Nachricht vormerken (ersetzt eine vorgemerkte).
// Laeuft nichts (mehr), geht sie wie gewohnt als Auftrag raus. Liefert null oder den Grund.
export async function chatVormerken(nachricht: string, kontext: ChatKontext): Promise<string | null> {
  const { start, chat } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  if (!laufenderChat(chat)) return chatAbschicken(nachricht, kontext);
  return vormerkungSetzen(start, nachricht, kontext);
}

// PUT an die Vormerkung: 'wartet' = steht als Karte da, 'offen' = lief nichts, ist gestartet.
async function vormerkungSetzen(start: Start, nachricht: string, kontext: ChatKontext): Promise<string | null> {
  const r = await vormerken(start, nachricht, kontext);
  if (!r.ok) {
    chatAbfragen();
    return r.grund;
  }
  if (r.status === 'offen') {
    // Es lief nichts (mehr): die Nachricht ist sofort als normaler Auftrag gestartet.
    auftragEintragen(r.id, nachricht, { vorgemerkt: null });
    return null;
  }
  const jetzt = pultStore.getState().chat;
  if (jetzt) pultStore.setState({ chat: { ...jetzt, vorgemerkt: { id: r.id, nachricht } } });
  return null;
}

export async function vormerkungLoeschenAuftrag(): Promise<string | null> {
  const { start } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  const r = await vormerkungLoeschen(start);
  if (!r.ok) return r.grund;
  const jetzt = pultStore.getState().chat;
  if (jetzt) pultStore.setState({ chat: { ...jetzt, vorgemerkt: null } });
  return null;
}

// Nach Fehler oder Stopp bleibt die Vormerkung stehen; "Starten" schickt sie von Hand los.
export async function vormerkungStartenAuftrag(): Promise<string | null> {
  const { start, chat } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  if (chat?.laeuft) return 'Der Assistent arbeitet gerade';
  const nachricht = chat?.vorgemerkt?.nachricht ?? '';
  const grund = await vorDemStart();
  if (grund) return grund;
  const r = await vormerkungStarten(start);
  if (!r.ok) {
    chatAbfragen();
    return r.grund;
  }
  auftragEintragen(r.auftrag, nachricht, { vorgemerkt: null });
  return null;
}

// Stopp des laufenden Chat-Auftrags; danach zeigt die Abfrage "wird gestoppt …" bis zum Abschluss.
export async function chatStoppen(art: StoppArt): Promise<string | null> {
  const { start, chat } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  const r = await stoppen(start, art, laufenderChat(chat)?.id);
  chatAbfragen();
  return r.ok ? null : r.grund;
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
