import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ChatEintrag, rueckgaengigFuer } from '../../chat';

import { Eintrag, rundenZeile, RundenAktionen, WARTET_TEXT } from './Runde';

function e(teil: Partial<ChatEintrag>): ChatEintrag {
  return { id: 'a', art: 'chat', nachricht: 'Bitte', antwort: '', status: 'in_arbeit', hinweise: [], ergebnis: {},
    fassung_vorher: 3, fassung_nachher: null, erstellt_am: 't', denken: '', schritte: [], schritt: '', schritt_nr: 0,
    stopp: null, bild_hinweise: [], ...teil };
}

const a = (teil: Partial<RundenAktionen> = {}): RundenAktionen => ({
  rueckSperre: null, rueckId: null, rueckLaeuft: null, fehlerAn: null, onRueckgaengig: () => {}, onExport: () => {},
  onStopp: () => {}, nurLesen: false, getrennt: false, gedankenSichtbar: true, gedankenUmschalten: () => {}, ...teil,
});
const html = (x: ChatEintrag, ak: RundenAktionen = a()) => renderToStaticMarkup(<Eintrag e={x} a={ak} />);

describe('Runden im Verlauf', () => {
  it('mehrere laufende Einträge: jeder mit eigener Schrittzeile, eigenen Gedanken und eigenem Stopp', () => {
    const eins = html(e({ id: 'r1', nachricht: 'Titel kürzer', schritt: 'Titel kürzen', schritt_nr: 2, denken: 'Denke an den Titel' }));
    const zwei = html(e({ id: 'r2', nachricht: 'Farbe wärmer', schritt: 'Farbe setzen', schritt_nr: 1, denken: 'Denke an die Farbe' }));
    expect(eins).toContain('Schritt 2 · Titel kürzen');
    expect(eins).toContain('Denke an den Titel');
    expect(eins).not.toContain('Denke an die Farbe');
    expect(eins).toContain('aria-label="Stopp: Titel kürzer"');
    expect(zwei).toContain('Schritt 1 · Farbe setzen');
    expect(zwei).toContain('aria-label="Stopp: Farbe wärmer"');
  });

  it('„wartet auf freien Platz“ mit eigenem Knopf, ohne Gedanken', () => {
    const w = html(e({ status: 'wartet', nachricht: 'Vierte Bitte' }));
    expect(w).toContain(WARTET_TEXT);
    expect(w).toContain('aria-label="Stopp: Vierte Bitte"');
    expect(w).not.toContain('Denkt nach');
  });

  it('Schrittzeile: gestoppt, getrennt, noch ohne Schritt', () => {
    expect(rundenZeile(e({ stopp: 'behalten' }), false)).toBe('Wird gestoppt …');
    expect(rundenZeile(e({}), true)).toBe('Verbindung …');
    expect(rundenZeile(e({ status: 'offen' }), false)).toBe('Wartet auf den Assistenten …');
    expect(rundenZeile(e({}), false)).toBe('Agent denkt nach …');
  });

  it('Rückgängig nur an der Runde mit der neuesten Fassung', () => {
    const spaet = e({ id: 'spaet', status: 'fertig', fassung_nachher: 7 });
    const frueh = e({ id: 'frueh', status: 'fertig', fassung_nachher: 6 });
    const ak = a({ rueckId: rueckgaengigFuer([spaet, frueh], 7) });
    expect(html(spaet, ak)).toContain('Rückgängig');
    expect(html(frueh, ak)).not.toContain('Rückgängig');
    expect(html(frueh, ak)).toContain('Spätere Änderungen vorhanden');
  });

  it('übersprungene Änderungen und gescheiterte Bildaufträge stehen als Hinweise am Eintrag', () => {
    const x = html(e({ status: 'fertig', antwort: 'Erledigt.', hinweise: ['Übersprungen, weil eine andere Runde inzwischen den Entwurf geändert hat: Titel'],
      bild_hinweise: ['Bild für held nicht erzeugt: Zeitüberschreitung'] }));
    expect(x).toContain('Übersprungen, weil eine andere Runde inzwischen den Entwurf geändert hat: Titel');
    expect(x).toContain('Bild für held nicht erzeugt: Zeitüberschreitung');
  });

  it('nur lesend: kein Stopp', () => {
    expect(html(e({ nachricht: 'X' }), a({ nurLesen: true }))).not.toContain('Stopp: X');
  });
});
