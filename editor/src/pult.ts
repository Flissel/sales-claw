// Anbindung des Editors an das Marketing-Pult (sales-claw Spec
// 2026-09-29-newsletter-editor-design.md §3.1). Einzige Stelle mit Netzverkehr:
// nur relative Adressen von sales-ui.
import type { Auftrag } from './bildfeld';
import type { Gestaltung } from './gestaltung';

export type Dokument = Record<string, unknown>;

// Firma (Mandant) eines Newsletters und Ziel der Bildzuordnung.
export type Firma = { id: string; name: string };

export type Rueckmeldung = { text: string; von: string; am: string; fassung: number };

export type Start = {
  dokument: Dokument;
  betreff: string;
  vorschautext: string;
  basis_fassung: number;
  speichern_url: string;
  vorschau_url: string;
  medien_url: string;
  // Firma dieses Newsletters und Zuordnung der Bilder zu Firmen; fehlen bei aelterem sales-ui.
  // null = Inhalt ohne Firma (alter Entwurf): kein Etikett, nie eine Vorgabe-Firma.
  mandant?: Firma | null;
  medien_zuordnung_url?: string;
  // Bilder aus der Bibliothek loeschen (01.10.2026); fehlt bei aelterem sales-ui.
  medien_loeschen_url?: string;
  bild_url: string;
  // Gestaltungsflaeche flachrechnen (Spec 2026-10-02 §5).
  gestaltung_url: string;
  stand_url: string;
  // Gestaltungs-Agent und Export (Spec 2026-10-02 §4, §6); Anbindung in chat.ts.
  chat_url: string;
  chat_stand_url: string;
  chat_rueckgaengig_url: string;
  // Live-Lauf (Spec 2026-10-02-newsletter-agent-live §3): Vormerken (PUT/DELETE), Starten, Stopp.
  chat_vormerkung_url: string;
  chat_vormerkung_starten_url: string;
  chat_stopp_url: string;
  // Anhaenge fuer den Chat (Spec 2026-10-06 §2.2); fehlt bei aelterem sales-ui.
  anhang_url?: string;
  export_vorschau_url: string;
  export_url: string;
  zurueck_url: string;
  csrf: string;
  // Freigabe (Spec 2026-10-07): Status des Newsletters, Einreichzeit, offene Rueckmeldungen
  // (neueste zuerst) und die Routen; fehlen bei aelterem sales-ui.
  status?: 'entwurf' | 'eingereicht';
  eingereicht_am?: string | null;
  rueckmeldungen?: Rueckmeldung[];
  einreichen_url?: string;
  zurueckziehen_url?: string;
  // Herkunft aus dem alten Freigabeweg (broadcast_proposals): Status und Kanal, sonst null.
  alter_weg?: { status?: string | null; kanal?: string | null } | null;
};

// Wie die Entwurfsseite (ui_marketing.py): nur solange der alte Weg noch offen ist.
export function alterWegHinweis(s: Pick<Start, 'alter_weg'>): string | null {
  const a = s.alter_weg;
  if (!a || (a.status !== 'draft' && a.status !== 'pending_approval')) return null;
  return (
    `Dieser Entwurf liegt noch im alten Freigabeweg (${a.kanal ?? ''}). Ablehnen hier stoppt ihn dort nicht, ` +
    'und Änderungen hier werden dort nicht verschickt. Im alten Weg ablehnen, falls er nicht rausgehen soll.'
  );
}

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

// Fehler im Inhalt (nicht im Netz) - der Text geht so an den Betreiber.
export class InhaltFehler extends Error {}

// Name der Mediendatei zu einer Anzeige-Adresse; null, wenn die Adresse keine
// Medien-Adresse ist oder sich nicht entschluesseln laesst (kaputtes %-Zeichen).
export function medienName(url: string): string | null {
  if (!url.startsWith(ANZEIGE)) return null;
  try {
    return decodeURIComponent(url.slice(ANZEIGE.length));
  } catch {
    return null;
  }
}

// Vor dem Speichern: nur Bloecke, die von root aus erreichbar sind (belt and
// braces zum rekursiven Loeschen - die DB lehnt verwaiste Bloecke ab), und
// Bilder zurueck auf "medien:<name>".
export function zurSpeicherung<T extends Dokument>(doc: T): T {
  return umschreiben(nurErreichbare(doc), (u) => {
    if (!u.startsWith(ANZEIGE)) return u;
    const name = medienName(u);
    if (name === null) throw new InhaltFehler('Bildadresse ungültig');
    return 'medien:' + name;
  });
}

function istObjekt(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

function kinderListe(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((k): k is string => typeof k === 'string') : [];
}

// Kinder eines Blocks auf den Pfaden des Editors (wie marketing.pult_bloecke_fehler):
// EmailLayout data.childrenIds, Container data.props.childrenIds,
// ColumnsContainer data.props.columns[].childrenIds.
export function kinderVon(block: unknown): string[] {
  if (!istObjekt(block) || !istObjekt(block.data)) return [];
  const data = block.data;
  const props = istObjekt(data.props) ? data.props : {};
  const ids = [...kinderListe(data.childrenIds), ...kinderListe(props.childrenIds)];
  if (Array.isArray(props.columns)) {
    for (const c of props.columns) if (istObjekt(c)) ids.push(...kinderListe(c.childrenIds));
  }
  return ids;
}

// Alle Bloecke, die von root aus erreichbar sind, in derselben Form; der Rest faellt weg.
export function nurErreichbare<T extends Dokument>(doc: T): T {
  const erreicht = new Set<string>();
  const offen = ['root'];
  while (offen.length > 0) {
    const id = offen.pop() as string;
    if (erreicht.has(id) || !(id in doc)) continue;
    erreicht.add(id);
    offen.push(...kinderVon(doc[id]));
  }
  const neu: Dokument = {};
  for (const [id, b] of Object.entries(doc)) if (erreicht.has(id)) neu[id] = b;
  return neu as T;
}

// Ein Block und alle seine Nachfahren (fuer das Loeschen im Block-Menue).
export function mitNachfahren(doc: Dokument, blockId: string): Set<string> {
  const weg = new Set<string>();
  const offen = [blockId];
  while (offen.length > 0) {
    const id = offen.pop() as string;
    if (weg.has(id)) continue;
    weg.add(id);
    offen.push(...kinderVon(doc[id]));
  }
  return weg;
}

// Meldung nach einem fehlgeschlagenen Speichern: der Grund ohne eigenen
// Schlusspunkt, damit nichts doppelt dasteht.
export function fehlerText(grund: string): string {
  const g = grund.trim().replace(/[\s.!]+$/u, '');
  return `Nicht gespeichert: ${g || 'unbekannter Grund'}. Deine Änderungen sind noch da.`;
}

function umschreiben<T extends Dokument>(doc: T, f: (u: string) => string): T {
  const neu = JSON.parse(JSON.stringify(doc)) as T;
  for (const b of Object.values(neu)) {
    // Bildblock und Container-Hintergrundbild (Spec 2026-10-01 §4: derselbe Ort props.url).
    if (!istObjekt(b) || (b.type !== 'Image' && b.type !== 'Container')) continue;
    if (!istObjekt(b.data) || !istObjekt(b.data.props)) continue;
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
  let dokument: Dokument;
  try {
    dokument = zurSpeicherung(doc);
  } catch (e) {
    return {
      ok: false,
      konflikt: false,
      grund: e instanceof InhaltFehler ? e.message : 'Das Dokument lässt sich nicht speichern',
    };
  }
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
        dokument,
        als_kopie: alsKopie,
      }),
    });
  } catch {
    return { ok: false, konflikt: false, grund: 'Keine Verbindung zum Pult' };
  }
  const j: unknown = await r.json().catch(() => ({}));
  const antwort = istObjekt(j) ? j : {};
  if (r.ok && typeof antwort.fassung === 'number') return { ok: true, fassung: antwort.fassung };
  const grund = typeof antwort.grund === 'string' && antwort.grund ? antwort.grund : 'Speichern gerade nicht möglich';
  return { ok: false, konflikt: r.status === 409, grund };
}

type SchrittErgebnis = { ok: true; eingereicht_am?: string } | { ok: false; grund: string };

async function freigabeSchritt(url: string | undefined, csrf: string, standardGrund: string): Promise<SchrittErgebnis> {
  if (!url) return { ok: false, grund: 'Das ist hier noch nicht eingerichtet' };
  try {
    const r = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': csrf },
      body: '{}',
    });
    const j: unknown = await r.json().catch(() => ({}));
    if (r.ok) {
      return istObjekt(j) && typeof j.eingereicht_am === 'string' && j.eingereicht_am
        ? { ok: true, eingereicht_am: j.eingereicht_am }
        : { ok: true };
    }
    return { ok: false, grund: istObjekt(j) && typeof j.grund === 'string' && j.grund ? j.grund : standardGrund };
  } catch {
    return { ok: false, grund: 'Keine Verbindung zum Pult' };
  }
}

// "07.10.2026, 09:30" in der Ortszeit; unlesbares Datum => unveraendert zurueck.
export function datumKurz(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function einreichen(s: Start) {
  return freigabeSchritt(s.einreichen_url, s.csrf, 'Einreichen gerade nicht möglich');
}

export function zurueckziehen(s: Start) {
  return freigabeSchritt(s.zurueckziehen_url, s.csrf, 'Zurückziehen gerade nicht möglich');
}

export type MedienStand = {
  bilder: string[];
  zuordnung: Record<string, string | null>;
  mandanten: Firma[];
  mandant: string;
  hinweis: string | null;
};

const ZUORDNUNG_AUS = 'Bildzuordnung nicht erreichbar';

// Etikett der Firma in der Pult-Leiste; null (kein Etikett) ohne Firma oder mit leerer id.
export function firmaEtikett(mandant: Firma | null | undefined): string | null {
  if (!mandant || typeof mandant.id !== 'string' || !mandant.id.trim()) return null;
  return mandant.name || mandant.id;
}

export const MEDIEN_LEER = 'Keine Bilder in den Medien. Bilder im Pult unter Medien hochladen.';

// Text einer geladenen Bildwahl ohne Bilder. Der Zuordnungs-Hinweis geht immer vor: dann ist die
// Bibliothek nicht leer, sondern ihre Zuordnung unbekannt. null = es gibt Bilder und keinen Hinweis.
export function leereBildwahl(anzahl: number, hinweis: string | null): string | null {
  if (hinweis) return hinweis;
  return anzahl === 0 ? MEDIEN_LEER : null;
}

function medienAusfall(): MedienStand {
  return { bilder: [], zuordnung: {}, mandanten: [], mandant: '', hinweis: ZUORDNUNG_AUS };
}

// Fehler oder Unverstaendliches => keine Bilder plus Hinweis (fail-closed).
export async function medienListe(s: Start): Promise<MedienStand> {
  try {
    const r = await fetch(s.medien_url, { credentials: 'same-origin' });
    if (!r.ok) return medienAusfall();
    const j: unknown = await r.json();
    if (!istObjekt(j) || !Array.isArray(j.bilder)) return medienAusfall();
    const zuordnung: Record<string, string | null> = {};
    if (istObjekt(j.zuordnung)) {
      for (const [n, m] of Object.entries(j.zuordnung)) {
        if (typeof m === 'string' || m === null) zuordnung[n] = m;
      }
    }
    const mandanten = Array.isArray(j.mandanten)
      ? j.mandanten.filter(istObjekt).flatMap((m) =>
          typeof m.id === 'string' && typeof m.name === 'string' ? [{ id: m.id, name: m.name }] : [],
        )
      : [];
    return {
      bilder: j.bilder.filter((b): b is string => typeof b === 'string' && medienNameOk(b)),
      zuordnung,
      mandanten,
      mandant: typeof j.mandant === 'string' ? j.mandant : '',
      hinweis: typeof j.hinweis === 'string' && j.hinweis ? j.hinweis : null,
    };
  } catch {
    return medienAusfall();
  }
}

// mandant null = Gemeinsam (nie "").
export async function medienZuordnen(
  s: Start,
  name: string,
  mandant: string | null,
): Promise<{ ok: true } | { ok: false; grund: string }> {
  if (!s.medien_zuordnung_url) return { ok: false, grund: 'Zuordnung ist hier noch nicht eingerichtet' };
  try {
    const r = await fetch(s.medien_zuordnung_url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': s.csrf },
      body: JSON.stringify({ name, mandant }),
    });
    const j: unknown = await r.json().catch(() => ({}));
    if (r.ok && istObjekt(j) && j.ok === true) return { ok: true };
    const grund = istObjekt(j) && typeof j.grund === 'string' && j.grund ? j.grund : 'Zuordnung gerade nicht möglich';
    return { ok: false, grund };
  } catch {
    return { ok: false, grund: 'Keine Verbindung zum Pult' };
  }
}

export async function bildBeauftragen(s: Start, platz: string, hinweis: string, staerke: number, neu: boolean): Promise<{ ok: true } | { ok: false; grund: string }> {
  try {
    const r = await fetch(s.bild_url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': s.csrf },
      body: JSON.stringify({ platz, hinweis, staerke, neu }),
    });
    if (r.ok) return { ok: true };
    const j: unknown = await r.json().catch(() => ({}));
    const grund = istObjekt(j) && typeof j.grund === 'string' && j.grund ? j.grund : 'Auftrag gerade nicht möglich';
    return { ok: false, grund };
  } catch {
    return { ok: false, grund: 'Keine Verbindung zum Pult' };
  }
}

export async function bildFreistellen(s: Start, platz: string): Promise<{ ok: true } | { ok: false; grund: string }> {
  try {
    const r = await fetch(s.bild_url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': s.csrf },
      body: JSON.stringify({ platz, freistellen: true }),
    });
    if (r.ok) return { ok: true };
    const j: unknown = await r.json().catch(() => ({}));
    const grund = istObjekt(j) && typeof j.grund === 'string' && j.grund ? j.grund : 'Freistellen gerade nicht möglich';
    return { ok: false, grund };
  } catch {
    return { ok: false, grund: 'Keine Verbindung zum Pult' };
  }
}

export type GestaltungErgebnis =
  | { ok: true; url: string; width: number; height: number; hinweise: string[] }
  | { ok: false; grund: string };

// Der Server prueft und rechnet die Flaeche zu einem Entwurfsbild (medien:gs-<hash12>.jpg).
export async function gestaltungRechnen(s: Start, g: Gestaltung): Promise<GestaltungErgebnis> {
  let r: Response;
  try {
    r = await fetch(s.gestaltung_url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': s.csrf },
      body: JSON.stringify({ gestaltung: g }),
    });
  } catch {
    return { ok: false, grund: 'Keine Verbindung zum Pult' };
  }
  const j: unknown = await r.json().catch(() => ({}));
  const a = istObjekt(j) ? j : {};
  if (!r.ok) {
    return { ok: false, grund: typeof a.grund === 'string' && a.grund ? a.grund : 'Gestaltung gerade nicht möglich' };
  }
  if (typeof a.url !== 'string' || !a.url.startsWith('medien:') || typeof a.width !== 'number' || typeof a.height !== 'number') {
    return { ok: false, grund: 'Antwort unverständlich' };
  }
  const hinweise = Array.isArray(a.hinweise) ? a.hinweise.filter((h): h is string => typeof h === 'string') : [];
  return { ok: true, url: a.url, width: a.width, height: a.height, hinweise };
}

export async function standLaden(s: Start): Promise<{ fassung: number; auftraege: Auftrag[] } | null> {
  try {
    const r = await fetch(s.stand_url, { credentials: 'same-origin' });
    if (!r.ok) return null;
    const j: unknown = await r.json();
    if (!istObjekt(j) || typeof j.fassung !== 'number' || !Array.isArray(j.auftraege)) return null;
    return { fassung: j.fassung, auftraege: j.auftraege.filter(istObjekt) as Auftrag[] };
  } catch {
    return null;
  }
}


export type LoeschInfo = { name: string; entwuerfe: number; sperre: string | null; newsletter: { titel: string; status: string }[] };

// Zwei Schritte wie die Medienseite: bestaetigt=false prueft nur (nichts wird geloescht).
export async function medienLoeschen(
  s: Start,
  name: string,
  bestaetigt: boolean,
): Promise<{ ok: true; info: LoeschInfo | null } | { ok: false; grund: string }> {
  if (!s.medien_loeschen_url) return { ok: false, grund: 'Löschen ist hier noch nicht eingerichtet' };
  try {
    const r = await fetch(s.medien_loeschen_url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': s.csrf },
      body: JSON.stringify({ name, bestaetigt }),
    });
    const j: unknown = await r.json().catch(() => ({}));
    if (!r.ok) {
      const grund = istObjekt(j) && typeof j.grund === 'string' && j.grund ? j.grund : 'Löschen gerade nicht möglich';
      return { ok: false, grund };
    }
    if (bestaetigt) return { ok: true, info: null };
    if (!istObjekt(j) || typeof j.name !== 'string') return { ok: false, grund: 'Antwort unverständlich' };
    const newsletter = Array.isArray(j.newsletter)
      ? j.newsletter.filter(istObjekt).map((v) => ({ titel: String(v.titel ?? ''), status: String(v.status ?? '') }))
      : [];
    return {
      ok: true,
      info: {
        name: j.name,
        entwuerfe: typeof j.entwuerfe === 'number' ? j.entwuerfe : 0,
        sperre: typeof j.sperre === 'string' && j.sperre ? j.sperre : null,
        newsletter,
      },
    };
  } catch {
    return { ok: false, grund: 'Keine Verbindung zum Pult' };
  }
}

// Text fuer die Rueckfrage vor dem Loeschen.
export function loeschFrage(info: LoeschInfo): string {
  const teile = [`„${info.name}“ endgültig aus den Medien löschen?`];
  if (info.entwuerfe > 0) {
    teile.push(`${info.entwuerfe} Sales-Entwurf/Entwürfe nennen diese Datei und scheitern danach beim Zustellen.`);
  }
  teile.push('Das lässt sich nicht rückgängig machen.');
  return teile.join(' ');
}
