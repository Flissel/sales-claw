// Einstieg der Seite /kalender: liest die Startdaten aus #kalender-start und
// baut FullCalendar (Woche/Tag/Monat/Liste) mit Ziehen, Anlegen und Bearbeiten.
import './kalender.css';

import { Calendar, type EventApi } from '@fullcalendar/core';
import deLocale from '@fullcalendar/core/locales/de';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';
import listPlugin from '@fullcalendar/list';
import timeGridPlugin from '@fullcalendar/timegrid';

import { braucheBestaetigung, type Ereignis, zuAenderung, zuEvent } from './abbild';
import { type Oberflaeche, schreiben } from './ablauf';
import * as api from './api';
import { grundOptionen, naechsteVolleStunde } from './einstellungen';
import { anlegenOeffnen, bearbeitenOeffnen, detailsOeffnen, konfliktFragen, type Kontext, zeitText } from './fenster';

interface Start {
  csrf: string;
  rolle: string;
  darf_schreiben: boolean;
  datum: string;
  ansicht: string;
  freigaben_url: string;
  neu_kunde?: { lead_id: string; name: string };
}

const SCHLUESSEL = 'vibemind.kalender.ansicht';
const ANSICHTEN = ['timeGridDay', 'timeGridWeek', 'dayGridMonth', 'listWeek'];
const AUS_URL: Record<string, string> = { tag: 'timeGridDay', woche: 'timeGridWeek', monat: 'dayGridMonth', liste: 'listWeek' };

function startdaten(): Start | null {
  const roh = document.getElementById('kalender-start')?.textContent;
  if (!roh) return null;
  try {
    return JSON.parse(roh) as Start;
  } catch {
    return null;
  }
}

function anfangsAnsicht(start: Start): string {
  // Ausdruecklich in der Adresse verlangt (?ansicht=) geht vor dem Gemerkten.
  if (new URLSearchParams(window.location.search).has('ansicht') && AUS_URL[start.ansicht]) return AUS_URL[start.ansicht];
  try {
    const gemerkt = window.localStorage.getItem(SCHLUESSEL);
    if (gemerkt && ANSICHTEN.includes(gemerkt)) return gemerkt;
  } catch {
    /* Speicher gesperrt (privates Fenster) - Rueckfall */
  }
  return window.innerWidth < 640 ? 'listWeek' : 'timeGridWeek';
}

function leisten(wurzel: HTMLElement) {
  const ladeHinweise = document.createElement('div');
  ladeHinweise.className = 'vk-leiste vk-leiste-laden';
  ladeHinweise.hidden = true;
  const meldungen = document.createElement('div');
  meldungen.className = 'vk-meldungen';
  meldungen.setAttribute('aria-live', 'polite');
  wurzel.before(ladeHinweise, meldungen);

  return {
    laden(texte: string[]) {
      ladeHinweise.textContent = texte.join(' · ');
      ladeHinweise.hidden = texte.length === 0;
    },
    melden(text: string, link?: string) {
      const zeile = document.createElement('div');
      zeile.className = 'vk-leiste';
      const t = document.createElement('span');
      t.textContent = text;
      zeile.append(t);
      if (link) {
        const a = document.createElement('a');
        a.href = link;
        a.textContent = 'Zu den Freigaben';
        zeile.append(' ', a);
      }
      const zu = document.createElement('button');
      zu.type = 'button';
      zu.className = 'vk-zu';
      zu.textContent = '×';
      zu.setAttribute('aria-label', 'Meldung schließen');
      zu.onclick = () => zeile.remove();
      zeile.append(zu);
      meldungen.prepend(zeile);
      while (meldungen.children.length > 4) meldungen.lastElementChild?.remove();
    },
  };
}

function starten(): void {
  const wurzel = document.getElementById('kalender');
  const start = startdaten();
  if (!wurzel || !start) return;
  api.einrichten(start.csrf);
  const leiste = leisten(wurzel);
  const darf = start.darf_schreiben === true;
  // eslint-artig vorab deklariert: die Oberflaeche braucht den Kalender zum Neuladen.
  let kalender: Calendar | null = null;
  const ui: Oberflaeche = {
    konfliktFragen,
    melden: (text, link) => leiste.melden(text, link),
    neuLaden: () => kalender?.refetchEvents(),
  };
  const ctx: Kontext = { darfSchreiben: darf, rolle: start.rolle, freigabenUrl: start.freigaben_url || '/freigaben', ui };

  async function verschoben(ev: EventApi, zurueck: () => void): Promise<void> {
    const art = String(ev.extendedProps.art);
    const neu = zuAenderung(ev);
    if (braucheBestaetigung(art)
        && !window.confirm(`Verschieben auf ${zeitText(ev.start as Date, ev.end)} – Entwurf an Kunden wird angelegt`)) {
      zurueck();
      return;
    }
    const geaendert_am = ev.extendedProps.geaendert_am as string | undefined;
    const ok = await schreiben(
      (trotzdem) => api.aendern(ev.id, { ...neu, ...(geaendert_am ? { geaendert_am } : {}), trotzdem }),
      ui, ctx.freigabenUrl);
    if (!ok) zurueck();
  }

  kalender = new Calendar(wurzel, {
    plugins: [dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin],
    locale: deLocale,
    initialView: anfangsAnsicht(start),
    initialDate: start.datum || undefined,
    ...grundOptionen(darf),
    customButtons: darf ? {
      neu: {
        text: 'Neu',
        hint: 'Neuer Termin',
        click: () => {
          const beginn = naechsteVolleStunde(new Date());
          anlegenOeffnen(beginn, new Date(beginn.getTime() + 60 * 60000), false, ctx);
        },
      },
    } : {},
    events: (info, ok, fehler) => {
      api.laden(info.startStr, info.endStr).then((r) => {
        if (!r.ok) {
          leiste.laden([r.daten.grund ?? 'Termine nicht abrufbar']);
          fehler(new Error(r.daten.grund ?? 'Termine nicht abrufbar'));
          return;
        }
        const hinweise = Array.isArray(r.daten.hinweise) ? (r.daten.hinweise as string[]) : [];
        leiste.laden(hinweise);
        const liste = Array.isArray(r.daten.ereignisse) ? (r.daten.ereignisse as Ereignis[]) : [];
        ok(liste.map((e) => zuEvent(e, darf)));
      }, (e: unknown) => fehler(e instanceof Error ? e : new Error(String(e))));
    },
    select: (info) => {
      kalender?.unselect();
      anlegenOeffnen(info.start, info.end, info.allDay, ctx);
    },
    eventClick: (info) => {
      info.jsEvent.preventDefault();
      const p = info.event.extendedProps;
      if (darf && p.bearbeitbar && (p.art === 'eigen' || p.art === 'kunde')) bearbeitenOeffnen(info.event, ctx);
      else detailsOeffnen(info.event, ctx);
    },
    eventDrop: (info) => { void verschoben(info.event, info.revert); },
    eventResize: (info) => { void verschoben(info.event, info.revert); },
    datesSet: (info) => {
      try {
        window.localStorage.setItem(SCHLUESSEL, info.view.type);
      } catch {
        /* Speicher gesperrt - nur eine Bequemlichkeit */
      }
    },
  });
  kalender.render();
  if (start.neu_kunde && darf) {
    const beginn = naechsteVolleStunde(new Date());
    anlegenOeffnen(beginn, new Date(beginn.getTime() + 60 * 60000), false, ctx,
      { art: 'kunde', kunde: start.neu_kunde });
    // Query entfernen, damit ein Neuladen den Dialog nicht erneut oeffnet.
    try {
      const u = new URL(window.location.href);
      u.searchParams.delete('neu');
      u.searchParams.delete('lead_id');
      window.history.replaceState(null, '', u.pathname + u.search + u.hash);
    } catch {
      /* ohne History-API bleibt die Query stehen */
    }
  }
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', starten);
else starten();
