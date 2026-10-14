// Feste Kalender-Optionen (ohne Rueckrufe), getrennt von main.ts, damit sie
// ohne DOM getestet werden koennen.
import type { CalendarOptions } from '@fullcalendar/core';

export function grundOptionen(darfSchreiben: boolean): CalendarOptions {
  return {
    // Die Symbol-Schrift "fcicons" steckt als data:-URL im Paket; die CSP der Seite
    // (kein font-src) blockiert sie. Textknoepfe der de-Locale ("Zurück"/"Vor").
    buttonIcons: false,
    firstDay: 1,
    allDaySlot: false,
    // Ganzer Tag im Zeitraster; sichtbar ist etwa 07–20 Uhr, der Rest per Scrollen.
    slotMinTime: '00:00',
    slotMaxTime: '24:00',
    scrollTime: '07:00',
    contentHeight: 600,
    businessHours: { daysOfWeek: [1, 2, 3, 4, 5], startTime: '08:00', endTime: '18:00' },
    nowIndicator: true,
    headerToolbar: {
      left: darfSchreiben ? 'prev,next today neu' : 'prev,next today',
      center: 'title',
      right: 'timeGridDay,timeGridWeek,dayGridMonth,listWeek',
    },
    selectable: darfSchreiben,
    selectMirror: darfSchreiben,
    editable: darfSchreiben,
    eventDurationEditable: darfSchreiben,
  };
}

/** Vorgabe fuer "Neu": die naechste volle Stunde nach `jetzt`. */
export function naechsteVolleStunde(jetzt: Date): Date {
  return new Date(jetzt.getFullYear(), jetzt.getMonth(), jetzt.getDate(), jetzt.getHours() + 1, 0);
}
