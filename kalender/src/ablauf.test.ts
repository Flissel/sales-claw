import { describe, expect, it, vi } from 'vitest';

import { ENTWURF_ANGELEGT, schreiben, VERALTET } from './ablauf';
import type { Ergebnis } from './api';

function oberflaeche(antwortAufKonflikt = true) {
  return {
    konfliktFragen: vi.fn(async () => antwortAufKonflikt),
    melden: vi.fn(),
    neuLaden: vi.fn(),
  };
}
const ok = (daten: Record<string, unknown> = {}): Ergebnis => ({ ok: true, status: 200, daten });
const konflikt: Ergebnis = { ok: false, status: 409, daten: { grund: 'Konflikt', konflikte: [], unvollstaendig: false } };

describe('schreiben', () => {
  it('Konflikt + trotzdem speichern -> zweite Anfrage mit trotzdem', async () => {
    const anfrage = vi.fn(async (t: boolean) => (t ? ok() : konflikt));
    const ui = oberflaeche(true);
    expect(await schreiben(anfrage, ui, '/freigaben')).toBe(true);
    expect(anfrage.mock.calls).toEqual([[false], [true]]);
    expect(ui.neuLaden).toHaveBeenCalled();
  });

  it('Konflikt + abbrechen -> false, keine zweite Anfrage', async () => {
    const anfrage = vi.fn(async () => konflikt);
    expect(await schreiben(anfrage, oberflaeche(false), '/freigaben')).toBe(false);
    expect(anfrage).toHaveBeenCalledTimes(1);
  });

  it('veraltet -> Hinweis und neu laden', async () => {
    const ui = oberflaeche();
    const r = await schreiben(async () => ({ ok: false, status: 409, daten: { grund: VERALTET } }), ui, '/f');
    expect(r).toBe(false);
    expect(ui.melden).toHaveBeenCalledWith(VERALTET);
    expect(ui.neuLaden).toHaveBeenCalled();
    expect(VERALTET).toBe('inzwischen geändert – neu laden');
  });

  it('Erfolg mit Entwurf -> Hinweis mit Link in die Freigaben', async () => {
    const ui = oberflaeche();
    await schreiben(async () => ok({ entwurf: { draft_id: '1', kanal: 'email' } }), ui, '/freigaben');
    expect(ui.melden).toHaveBeenCalledWith(ENTWURF_ANGELEGT, '/freigaben');
    expect(ENTWURF_ANGELEGT).toBe('Entwurf an Kunde angelegt – in Freigaben');
  });

  it('Erfolg mit Hinweis (kein Kanal) zeigt ihn', async () => {
    const ui = oberflaeche();
    await schreiben(async () => ok({ hinweis: 'kein Kanal zum Kunden – bitte selbst Bescheid geben' }), ui, '/f');
    expect(ui.melden).toHaveBeenCalledWith('kein Kanal zum Kunden – bitte selbst Bescheid geben');
  });

  it('503 zeigt den Grund und laedt neu (Aenderung kann geschehen sein)', async () => {
    const ui = oberflaeche();
    const grund = 'Termin geändert, aber Entwurf an den Kunden nicht angelegt – bitte selbst Bescheid geben';
    expect(await schreiben(async () => ({ ok: false, status: 503, daten: { grund } }), ui, '/f')).toBe(false);
    expect(ui.melden).toHaveBeenCalledWith(grund);
    expect(ui.neuLaden).toHaveBeenCalled();
  });

  it('422 zeigt nur den Grund', async () => {
    const ui = oberflaeche();
    await schreiben(async () => ({ ok: false, status: 422, daten: { grund: 'Dauer muss 15–480 Minuten sein' } }), ui, '/f');
    expect(ui.melden).toHaveBeenCalledWith('Dauer muss 15–480 Minuten sein');
    expect(ui.neuLaden).not.toHaveBeenCalled();
  });

  it('503 mit gespeichertem Termin (Entwurf gescheitert) gilt als gespeichert: Fenster zu, Meldung, neu laden', async () => {
    const ui = oberflaeche();
    const grund = 'Termin geändert, aber Entwurf an den Kunden nicht angelegt – bitte selbst Bescheid geben';
    const r = await schreiben(async () => ({ ok: false, status: 503, daten: { grund, ereignis: { id: 'kunde:neu' } } }), ui, '/f');
    expect(r).toBe(true);
    expect(ui.melden).toHaveBeenCalledWith(grund);
    expect(ui.neuLaden).toHaveBeenCalled();
  });

  it('503 nach erfolgter Absage (geloescht) gilt ebenfalls als gespeichert', async () => {
    const ui = oberflaeche();
    const r = await schreiben(async () => ({ ok: false, status: 503, daten: { grund: 'Termin abgesagt, aber …', geloescht: true } }), ui, '/f');
    expect(r).toBe(true);
  });
});
