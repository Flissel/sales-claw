// Abbildung zwischen der JSON-Form von /kalender/termine.json (kalender_sicht.ereignisse)
// und den Ereignissen von FullCalendar. Reine Funktionen, ohne DOM.
import type { EventApi, EventInput } from '@fullcalendar/core';

export type Art = 'kunde' | 'eigen' | 'kollege' | 'handy';

export interface Ereignis {
  id: string;
  art: Art;
  titel: string;
  beginn: string;
  ende: string;
  bearbeitbar: boolean;
  uid?: string;
  lead_id?: string;
  kontakt?: string;
  ort?: string;
  notiz?: string;
  quelle?: string;
  geaendert_am?: string;
  // Nur in Schreib-Antworten oder kuenftigen Feldern: NULL = noch nicht abgeglichen.
  kalender_stand?: string | null;
}

export const FARBEN: Record<Art, string> = {
  kunde: 'var(--marke, #b45309)',
  eigen: '#2563eb',
  kollege: '#4d7c5a',
  handy: '#9ca3af',
};

export const NICHT_IM_HANDY = 'nicht im Handy-Kalender';
export const TRENNER = ' – ';

/** Nur ein Abgleich, der ausdruecklich fehlgeschlagen ist, zaehlt; NULL ist unbekannt. */
export function handyFehlt(stand: string | null | undefined): boolean {
  return typeof stand === 'string' && stand.startsWith('fehlgeschlagen');
}

/** Thema eines Kundentermins: der Titel ohne das angehaengte " – Kontakt". */
export function themaAus(e: Pick<Ereignis, 'titel' | 'kontakt'>): string {
  const endung = e.kontakt ? `${TRENNER}${e.kontakt}` : '';
  return endung && e.titel.endsWith(endung) ? e.titel.slice(0, -endung.length) : e.titel;
}

function titelVon(e: Ereignis): string {
  let t = e.titel;
  if (e.art === 'kunde' && e.kontakt && !t.includes(e.kontakt)) t = `${t}${TRENNER}${e.kontakt}`;
  if (e.art === 'kollege' && e.quelle) t = `${t} (${e.quelle})`;
  if (handyFehlt(e.kalender_stand)) t = `${t} · ${NICHT_IM_HANDY}`;
  return t;
}

export function zuEvent(e: Ereignis, darfSchreiben = true): EventInput {
  const editable = darfSchreiben && e.bearbeitbar && (e.art === 'kunde' || e.art === 'eigen');
  return {
    id: e.id,
    title: titelVon(e),
    start: e.beginn,
    end: e.ende,
    editable,
    color: FARBEN[e.art] ?? FARBEN.handy,
    classNames: [`vk-${e.art}`],
    extendedProps: {
      art: e.art,
      uid: e.uid ?? '',
      lead_id: e.lead_id ?? '',
      kontakt: e.kontakt ?? '',
      ort: e.ort ?? '',
      notiz: e.notiz ?? '',
      quelle: e.quelle ?? '',
      geaendert_am: e.geaendert_am,
      thema: e.art === 'kunde' ? themaAus(e) : e.titel,
      bearbeitbar: e.bearbeitbar,
      handy_fehlt: handyFehlt(e.kalender_stand),
    },
  };
}

function zwei(n: number): string {
  return String(n).padStart(2, '0');
}

/** Lokale Wandzeit mit dem fuer DIESEN Zeitpunkt gueltigen Offset (Sommer-/Winterzeit). */
export function isoMitOffset(d: Date): string {
  const versatz = -d.getTimezoneOffset();
  const vz = versatz >= 0 ? '+' : '-';
  const a = Math.abs(versatz);
  return `${d.getFullYear()}-${zwei(d.getMonth() + 1)}-${zwei(d.getDate())}T${zwei(d.getHours())}:${zwei(d.getMinutes())}:${zwei(d.getSeconds())}${vz}${zwei(Math.floor(a / 60))}:${zwei(a % 60)}`;
}

/** Datum ("YYYY-MM-DD") + Uhrzeit ("HH:MM") als lokale Wandzeit -> ISO mit Offset. */
export function lokalZuIso(datum: string, zeit: string): string {
  const [j, m, t] = datum.split('-').map(Number);
  const [h, min] = zeit.split(':').map(Number);
  return isoMitOffset(new Date(j, m - 1, t, h, min));
}

export function zuAenderung(
  ev: Pick<EventApi, 'start' | 'end'>,
  standardMinuten = 60,
): { beginn: string; dauer_minuten: number } {
  if (!ev.start) throw new Error('Termin ohne Beginn');
  const dauer = ev.end ? Math.round((ev.end.getTime() - ev.start.getTime()) / 60000) : standardMinuten;
  return { beginn: isoMitOffset(ev.start), dauer_minuten: dauer };
}

/** Aenderungen an Kundenterminen legen einen Entwurf an den Kunden an -> vorher fragen. */
export function braucheBestaetigung(art: string): boolean {
  return art === 'kunde';
}
