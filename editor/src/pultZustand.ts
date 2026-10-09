import { create } from 'zustand';

import { ladeEntscheid, neuesBildMeldung } from './bildfeld';
import type { Auftrag } from './bildfeld';
import {
  anhangHochladen,
  ChatEintrag,
  ChatKontext,
  chatLaden,
  chatSenden,
  ChatStand,
  exportLaeuft,
  laufendeRunden,
  neueFassungNachChat,
  rueckgaengig,
  sperrText,
  stoppen,
  StoppArt,
} from './chat';
import {
  AnhangChip,
  AuswahlChip,
  chipHinzu,
  chipsBereinigen,
  dateiPruefen,
  entferntHinweis,
  kontextBauen,
  kontextBytes,
  kurzText,
  MAX_ANHAENGE,
  MAX_AUSWAHL,
  sendenErlaubt,
} from './chatKontext';
import { getDocument, resetDocument, setDocument, setSelectedBlockId } from './documents/editor/EditorContext';
import type { Ebene } from './gestaltung';
import type { TEditorConfiguration } from './documents/editor/core';
import { anzeigbar, zuletztGeaendert } from './live';

// Liegt zur Freigabe: der Editor ist nur lesend (Zurueckziehen hebt es auf).
export const LIEGT_ZUR_FREIGABE = 'Liegt zur Freigabe – erst zurückziehen';
import { Dokument, einreichen, Ergebnis, fehlerText, Firma, markeHinweisAus, medienListe, speichern, standLaden, Start, zurAnzeige } from './pult';

// Zustand der Pult-Leiste: Startdaten, Betreff/Vorschautext, gemerkte Fassung
// und ob seit dem letzten Speichern etwas geaendert wurde.
type TPult = {
  start: Start | null;
  betreff: string;
  vorschautext: string;
  basis: number;
  ungespeichert: boolean;
  medien: string[] | null;
  // Zuordnung der Bilder zu Firmen (null = Gemeinsam), Firmenliste und Hinweis des Servers (Bildwahl).
  medienZuordnung: Record<string, string | null>;
  mandanten: Firma[];
  medienHinweis: string | null;
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
  // Chips ueber dem Chat-Eingabefeld (Spec 2026-10-06): markierte Bloecke/Ebenen und Anhaenge fuer
  // die naechste Nachricht.
  chatAuswahl: AuswahlChip[];
  chatAnhaenge: AnhangChip[];
  // Text im Chat-Eingabefeld (überlebt das Neuladen nach einer Agenten-Fassung).
  chatText: string;
  // Kurzer Hinweis am Eingabefeld (Chip abgelehnt, markierte Elemente weggefallen); null = keiner.
  chatHinweis: string | null;
  // Liegt zur Freigabe: Canvas, Werkzeuge, Inspector und Chat sind gesperrt (Zurueckziehen hebt es auf).
  nurLesen: boolean;
};

export const pultStore = create<TPult>(() => ({
  start: null,
  betreff: '',
  vorschautext: '',
  basis: 0,
  ungespeichert: false,
  medien: null,
  medienZuordnung: {},
  mandanten: [],
  medienHinweis: null,
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
  chatAuswahl: [],
  chatAnhaenge: [],
  chatText: '',
  chatHinweis: null,
  nurLesen: false,
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
    nurLesen: start.status === 'eingereicht',
  });
}

// "Zur Freigabe einreichen": nicht, solange der Assistent arbeitet; Ungespeichertes wird vorher
// gespeichert. Erfolg sperrt den Editor. Liefert null oder den Grund fuer den Betreiber.
export async function einreichenAuftrag(): Promise<string | null> {
  const { start, chat, hinweisOffen, ungespeichert } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  // Dasselbe Kriterium wie die Sperre in der Oberflaeche (Agent oder Newsletter-Export).
  if (sperrText(chat) !== null) return 'Der Assistent arbeitet gerade';
  if (hinweisOffen) return HINWEIS_OFFEN;
  if (ungespeichert) {
    const e = await newsletterSichern(false);
    if (!e.ok) return fehlerText(e.grund);
  }
  const r = await einreichen(start);
  if (!r.ok) return r.grund;
  // Zeit vom Server, wenn er sie mitschickt; sonst die Uhr dieses Rechners.
  const am = r.eingereicht_am ?? new Date().toISOString();
  // Einreichen erledigt offene Rueckmeldungen (DB) - das Feedback-Band verschwindet sofort.
  pultStore.setState({
    start: { ...start, status: 'eingereicht', eingereicht_am: am, rueckmeldungen: [] },
    nurLesen: true,
  });
  return null;
}

// Marke per Chat: Band "Die Marke hat sich geändert". Nicht bei nurLesen/eingereicht.
export const MARKE_BITTE = 'Übernimm die neue Marke: Farben, Schriften und Logo, sonst nichts ändern.';

export function markeBandSichtbar(start: Start | null, nurLesen: boolean): boolean {
  return !!start && start.marke_geaendert === true && start.status !== 'eingereicht' && !nurLesen;
}

function markeBandWeg() {
  const { start } = pultStore.getState();
  if (start) pultStore.setState({ start: { ...start, marke_geaendert: false } });
}

// "Übernehmen": die Bitte geht wörtlich über den Chat-Weg an den Agenten. Liefert null oder den Grund.
export async function markeUebernehmen(): Promise<string | null> {
  const grund = await chatAbschicken(MARKE_BITTE, { fenster: 'newsletter', auswahl: null });
  if (grund) return grund;
  markeBandWeg();
  return null;
}

// "Ausblenden": die Markierung am Inhalt löschen. Nicht, solange der Assistent arbeitet.
export async function markeHinweisAusblenden(): Promise<string | null> {
  const { start, chat } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  if (sperrText(chat) !== null) return 'Der Assistent arbeitet gerade';
  const r = await markeHinweisAus(start);
  if (!r.ok) return r.grund;
  markeBandWeg();
  return null;
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
  medienLaeuft = medienListe(start).then((m) =>
    pultStore.setState({
      medien: m.bilder,
      medienZuordnung: m.zuordnung,
      mandanten: m.mandanten,
      medienHinweis: m.hinweis,
    }),
  );
}

const MERKZETTEL = 'vibemind-neues-bild';
const NEU_GELADEN = 'vibemind-neu-geladen';
const FENSTER = 'vibemind-fenster';
const CHAT_ENTWURF = 'vibemind-chat-entwurf';

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
    const { chatText } = pultStore.getState();
    if (chatText.trim()) sessionStorage.setItem(CHAT_ENTWURF, chatText);
  } catch {
    /* ohne Merkzettel wird nur neu geladen */
  }
  window.location.reload();
  return true;
}

export function chatTextSetzen(text: string) {
  pultStore.setState({ chatText: text });
}

// Nach dem Neuladen: ein angefangener Chat-Text steht wieder im Eingabefeld.
export function chatEntwurfWiederholen() {
  try {
    const text = sessionStorage.getItem(CHAT_ENTWURF);
    if (text === null) return;
    sessionStorage.removeItem(CHAT_ENTWURF);
    pultStore.setState({ chatText: text });
  } catch {
    /* kein Merkzettel */
  }
}

// Nach dem Neuladen: war ein Gestaltungsfenster offen, oeffnet es sich wieder.
export function fensterWiederOeffnen() {
  try {
    const id = sessionStorage.getItem(FENSTER);
    if (id === null) return;
    sessionStorage.removeItem(FENSTER);
    if (pultStore.getState().nurLesen) return;
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
  chipsAbgleichen();
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
      // Erst die neue Fassung (auch wenn schon die naechste Runde laeuft) - die Seite laedt neu.
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
    if (jetzt?.laeuft) chatTakt = setTimeout(holen, laufendeRunden(jetzt).length > 0 ? CHAT_TAKT_MS : EXPORT_TAKT_MS);
  };
  void holen();
}

// Vorlaeufiger Eintrag fuer einen eben gestarteten Auftrag: sperrt sofort und laesst
// neueFassungNachChat den Uebergang erkennen; danach wird abgefragt.
function auftragEintragen(id: string, nachricht: string, status: 'offen' | 'wartet') {
  const eintrag: ChatEintrag = {
    id, art: 'chat', nachricht, antwort: '', status, hinweise: [], ergebnis: {},
    fassung_vorher: status === 'wartet' ? null : pultStore.getState().basis, fassung_nachher: null,
    erstellt_am: new Date().toISOString(), denken: '', schritte: [], schritt: '', schritt_nr: 0, stopp: null,
    bild_hinweise: [],
  };
  const alt = pultStore.getState().chat;
  const verlauf = (alt?.verlauf ?? []).filter((e) => e.id !== id);
  pultStore.setState({ chat: { live: null, neueste: null, ...alt, laeuft: true, verlauf: [...verlauf, eintrag] } });
  chatAbfragen();
}

export const HINWEIS_OFFEN = 'Im Bildfeld steht noch ein Hinweis – erst beauftragen oder leeren';

// Nachricht an den Agenten. Ungesicherte Aenderungen am Newsletter werden vorher gespeichert -
// der Agent arbeitet mit der gespeicherten Fassung. Liefert null oder den Grund fuer den Betreiber.
// Die Chips gehen mit der Nachricht (kontext.auswahl/anhaenge) und werden danach geleert.
export async function chatAbschicken(nachricht: string, kontext: ChatKontext): Promise<string | null> {
  const { start, chat, nurLesen } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  if (nurLesen) return LIEGT_ZUR_FREIGABE;
  // Mehrere Runden duerfen laufen (Spec 2026-10-09 §2); nur ein Newsletter-Export am PC laeuft allein.
  if (exportLaeuft(chat)) return 'Der Assistent arbeitet gerade';
  const vorab = mitChips(kontext);
  if (!vorab.ok) return vorab.grund;
  const grund = await vorDemStart();
  if (grund) return grund;
  // Nach dem Speichern neu aufnehmen: was inzwischen dazukam, geht mit.
  const mit = mitChips(kontext);
  if (!mit.ok) return mit.grund;
  const r = await chatSenden(start, nachricht, mit.kontext);
  if (!r.ok) {
    // Z. B. arbeitet der Assistent schon fuer einen anderen Tab: Stand holen, damit die Sperre erscheint.
    chatAbfragen();
    return r.grund;
  }
  chipsVerbraucht(mit);
  auftragEintragen(r.auftrag, nachricht, r.status);
  return null;
}

// Momentaufnahme der Chips beim Senden: kontext mit ihnen und die Chips selbst (zum Leeren danach -
// was waehrend des Sendens dazukommt, bleibt fuer die naechste Nachricht stehen).
type MitChips = { ok: true; kontext: ChatKontext; auswahl: AuswahlChip[]; anhaenge: AnhangChip[] };
const KONTEXT_MAX = 4096;

// Vor dem Senden: markierte Elemente, die es im Dokument nicht mehr gibt (Agent, Rueckgaengig,
// Loeschen), fallen weg - mit Hinweis am Eingabefeld; die Nachricht geht trotzdem.
function mitChips(kontext: ChatKontext): MitChips | { ok: false; grund: string } {
  const { chatAnhaenge } = pultStore.getState();
  if (!sendenErlaubt(chatAnhaenge)) return { ok: false, grund: 'Erst warten, bis die Anhänge hochgeladen sind' };
  const { behalten: chatAuswahl, entfernt } = chipsBereinigen(pultStore.getState().chatAuswahl, getDocument(), null);
  if (entfernt > 0) pultStore.setState({ chatAuswahl, chatHinweis: entferntHinweis(entfernt) });
  const k = kontextBauen(chatAuswahl, chatAnhaenge);
  const neu: ChatKontext = { ...kontext };
  if (k.auswahl.length > 0) neu.auswahl = k.auswahl;
  if (k.anhaenge.length > 0) neu.anhaenge = k.anhaenge;
  if (kontextBytes(neu) > KONTEXT_MAX) return { ok: false, grund: 'Zu viel Kontext – entferne ein paar Chips' };
  return { ok: true, kontext: neu, auswahl: chatAuswahl, anhaenge: chatAnhaenge };
}

function chipsVerbraucht(mit: MitChips) {
  const { chatAuswahl, chatAnhaenge } = pultStore.getState();
  pultStore.setState({
    chatAuswahl: chatAuswahl.filter((c) => !mit.auswahl.includes(c)),
    chatAnhaenge: chatAnhaenge.filter((a) => !mit.anhaenge.some((m) => m.id === a.id)),
  });
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

// Das Dokument wurde ersetzt oder geaendert (Agent, Rueckgaengig, Loeschen): die Chip-Reihe zeigt nur,
// was es noch gibt. Nicht, solange ein Zwischenstand des Agenten gezeigt wird (das echte Dokument
// kommt danach zurueck - zwischenstandBeenden gleicht dann ab). In main.tsx an onDocumentChange.
export function chipsAbgleichen() {
  const { zwischenstand, chatAuswahl, gestaltungOffen } = pultStore.getState();
  if (zwischenstand !== null || chatAuswahl.length === 0) return;
  const { behalten, entfernt } = chipsBereinigen(chatAuswahl, getDocument(), gestaltungOffen);
  if (entfernt > 0) pultStore.setState({ chatAuswahl: behalten, chatHinweis: entferntHinweis(entfernt) });
}

// ─── Kontext-Chips (Alt+Klick / "+ Kontext") ────────────────────────────
// Liefern null oder den Grund fuer den Betreiber.

// Der Grund steht auch als Hinweis am Eingabefeld (Alt+Klick hat sonst keine Rueckmeldung).
function abgelehnt(grund: string): string {
  pultStore.setState({ chatHinweis: grund });
  return grund;
}

function auswahlHinzu(chip: AuswahlChip): string | null {
  const alt = pultStore.getState().chatAuswahl;
  const neu = chipHinzu(alt, chip);
  if (neu !== alt) {
    pultStore.setState({ chatAuswahl: neu, chatHinweis: null });
    return null;
  }
  const schonDa = alt.some((c) => c.art === chip.art && c.id === chip.id && (c.flaeche ?? '') === (chip.flaeche ?? ''));
  if (schonDa) return null;
  return abgelehnt(alt.length >= MAX_AUSWAHL ? `Höchstens ${MAX_AUSWAHL} markierte Elemente je Nachricht` : 'Dieses Element lässt sich nicht markieren');
}

export function blockAlsKontext(blockId: string): string | null {
  const block = blockId === 'root' ? undefined : getDocument()[blockId];
  if (!block) return abgelehnt('Diesen Block gibt es nicht mehr');
  return auswahlHinzu({ art: 'block', id: blockId, kurz: kurzText(block) });
}

export function chatHinweisWeg() {
  if (pultStore.getState().chatHinweis !== null) pultStore.setState({ chatHinweis: null });
}

export function ebeneAlsKontext(flaeche: string, e: Ebene): string | null {
  return auswahlHinzu({ art: 'ebene', id: e.id, flaeche, kurz: kurzText(e) });
}

export function auswahlEntfernen(chip: AuswahlChip) {
  pultStore.setState({ chatAuswahl: pultStore.getState().chatAuswahl.filter((c) => c !== chip) });
}

// "+ Kontext"-Tasten: an den Chat haengen bzw. (ist schon drin) wieder herausnehmen.
export function blockKontextUmschalten(blockId: string): string | null {
  const chip = pultStore.getState().chatAuswahl.find((c) => c.art === 'block' && c.id === blockId);
  if (!chip) return blockAlsKontext(blockId);
  auswahlEntfernen(chip);
  return null;
}

export function ebeneKontextUmschalten(flaeche: string, e: Ebene): string | null {
  const chip = pultStore.getState().chatAuswahl.find((c) => c.art === 'ebene' && c.id === e.id && c.flaeche === flaeche);
  if (!chip) return ebeneAlsKontext(flaeche, e);
  auswahlEntfernen(chip);
  return null;
}

// ─── Anhaenge (Bueroklammer, Ziehen, Einfuegen) ─────────────────────────

const uploads = new Map<string, () => void>();
let anhangNr = 0;

function anhangAendern(id: string, teil: Partial<AnhangChip>) {
  const liste = pultStore.getState().chatAnhaenge;
  if (!liste.some((a) => a.id === id)) return;
  pultStore.setState({ chatAnhaenge: liste.map((a) => (a.id === id ? { ...a, ...teil } : a)) });
}

// Legt sofort einen Chip an (falscher Typ / zu gross: mit Grund, ohne Upload) und laedt hoch.
// Liefert den Grund, wenn schon 5 Anhaenge dran sind (fehlerhafte zaehlen nicht).
export function anhangHinzu(datei: File): string | null {
  const { start, chatAnhaenge, nurLesen } = pultStore.getState();
  if (nurLesen) return LIEGT_ZUR_FREIGABE;
  if (chatAnhaenge.filter((a) => a.status !== 'fehler').length >= MAX_ANHAENGE) return `Höchstens ${MAX_ANHAENGE} Anhänge je Nachricht`;
  const id = `anhang-${++anhangNr}`;
  const p = dateiPruefen(datei);
  const chip: AnhangChip = { id, name: datei.name, art: 'art' in p ? p.art : 'dokument', status: 'laedt', fortschritt: 0 };
  const grund = 'grund' in p ? p.grund : start ? null : 'Keine Verbindung zum Pult';
  if (grund !== null || !start) {
    pultStore.setState({ chatAnhaenge: [...chatAnhaenge, { ...chip, status: 'fehler', grund: grund ?? undefined }] });
    return null;
  }
  pultStore.setState({ chatAnhaenge: [...chatAnhaenge, chip] });
  const h = anhangHochladen(start, datei, (f) => anhangAendern(id, { fortschritt: f }));
  uploads.set(id, h.abbrechen);
  void h.promise.then((r) => {
    uploads.delete(id);
    if (r.ok) anhangAendern(id, { name: r.name, art: r.art, status: 'fertig', fortschritt: 1 });
    else anhangAendern(id, { status: 'fehler', grund: r.grund });
  });
  return null;
}

export function anhangVorschau(id: string, vorschau: string) {
  anhangAendern(id, { vorschau });
}

// Entfernen bricht einen laufenden Upload ab (eine schon abgelegte Datei bleibt in den Medien).
export function anhangEntfernen(id: string) {
  const abbrechen = uploads.get(id);
  uploads.delete(id);
  pultStore.setState({ chatAnhaenge: pultStore.getState().chatAnhaenge.filter((a) => a.id !== id) });
  abbrechen?.();
}

// Stopp genau dieser Runde (Spec 2026-10-09: Stopp wirkt pro Runde); danach zeigt die Abfrage "wird gestoppt …".
export async function chatStoppen(art: StoppArt, auftrag: string): Promise<string | null> {
  const { start } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  const r = await stoppen(start, art, auftrag);
  chatAbfragen();
  return r.ok ? null : r.grund;
}

// Rueckgaengig legt die Fassung vor der Agenten-Antwort als neue Fassung an; danach neu laden.
export async function chatRueckgaengig(auftrag: string): Promise<string | null> {
  const { start, ungespeichert, hinweisOffen, chat, nurLesen } = pultStore.getState();
  if (!start) return 'Keine Verbindung zum Pult';
  if (nurLesen) return LIEGT_ZUR_FREIGABE;
  if (chat?.laeuft) return 'Der Assistent arbeitet gerade';
  if (hinweisOffen) return HINWEIS_OFFEN;
  if (ungespeichert) return 'Erst speichern – sonst gingen deine Änderungen verloren';
  const r = await rueckgaengig(start, auftrag);
  if (!r.ok) return r.grund;
  neueFassungLaden(r.fassung);
  return null;
}
