import { afterEach, describe, expect, it, vi } from 'vitest';

import { resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import { markeHinweisAus, Start } from './pult';
import { markeBandSichtbar, MARKE_BITTE, markeHinweisAusblenden, markeUebernehmen, pultStarten, pultStore } from './pultZustand';

const DOK = { root: { type: 'EmailLayout', data: { childrenIds: [] } } } as TEditorConfiguration;

function start(teil: Partial<Start> = {}): Start {
  return {
    dokument: DOK,
    betreff: 'B',
    vorschautext: 'V',
    basis_fassung: 2,
    speichern_url: '/s',
    chat_url: '/c',
    chat_stand_url: '/cs',
    marke_hinweis_aus_url: '/m',
    marke_geaendert: true,
    csrf: 'marke',
    status: 'entwurf',
    ...teil,
  } as Start;
}

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

function vorbereiten(teil: Partial<Start> = {}, zustand: Partial<ReturnType<typeof pultStore.getState>> = {}) {
  resetDocument(DOK);
  pultStarten(start(teil));
  pultStore.setState({ chat: null, ...zustand });
}

describe('markeHinweisAus (Fetch)', () => {
  it('POST mit X-CSRF an marke_hinweis_aus_url', async () => {
    const f = vi.fn(async () => antwort(200, { ok: true }));
    vi.stubGlobal('fetch', f);
    expect(await markeHinweisAus(start())).toEqual({ ok: true });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/m');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke');
  });

  it('Grund des Servers, kein Netz, fehlende Adresse', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(503, { grund: 'Marketing gerade nicht erreichbar' })));
    expect(await markeHinweisAus(start())).toEqual({ ok: false, grund: 'Marketing gerade nicht erreichbar' });
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('x'))));
    expect(await markeHinweisAus(start())).toEqual({ ok: false, grund: 'Keine Verbindung zum Pult' });
    expect((await markeHinweisAus(start({ marke_hinweis_aus_url: undefined }))).ok).toBe(false);
  });
});

describe('Band-Logik', () => {
  it('sichtbar nur bei marke_geaendert, ohne nurLesen', () => {
    expect(markeBandSichtbar(start(), false)).toBe(true);
    expect(markeBandSichtbar(start({ marke_geaendert: false }), false)).toBe(false);
    expect(markeBandSichtbar(start({ marke_geaendert: undefined }), false)).toBe(false);
    expect(markeBandSichtbar(start(), true)).toBe(false);
    expect(markeBandSichtbar(start({ status: 'eingereicht' }), false)).toBe(false);
    expect(markeBandSichtbar(null, false)).toBe(false);
  });
});

describe('Uebernehmen', () => {
  it('schickt die Bitte woertlich ueber den Chat-Weg; danach ist das Band weg', async () => {
    vorbereiten();
    expect(MARKE_BITTE).toBe('Übernimm die neue Marke: Farben, Schriften und Logo, sonst nichts ändern.');
    const f = vi.fn(async (url: string) => (url === '/c' ? antwort(200, { auftrag: 'c1' }) : antwort(200, {})));
    vi.stubGlobal('fetch', f);
    expect(await markeUebernehmen()).toBeNull();
    const chat = f.mock.calls.find((c) => (c as unknown as [string])[0] === '/c') as unknown as [string, RequestInit];
    expect(JSON.parse(String(chat[1].body)).nachricht).toBe(MARKE_BITTE);
    expect(pultStore.getState().start?.marke_geaendert).toBe(false);
  });

  it('gesperrt, solange ein Newsletter-Export laeuft: kein Netzaufruf, Band bleibt', async () => {
    vorbereiten({}, { chat: { laeuft: true, verlauf: [{ art: 'export', status: 'offen' } as never], live: null, neueste: null } });
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    expect(await markeUebernehmen()).toBe('Der Assistent arbeitet gerade');
    expect(f).not.toHaveBeenCalled();
    expect(pultStore.getState().start?.marke_geaendert).toBe(true);
  });

  it('Fehler beim Senden: Grund kommt zurueck, Band bleibt', async () => {
    vorbereiten();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Nicht moeglich' })));
    expect(await markeUebernehmen()).toBeTruthy();
    expect(pultStore.getState().start?.marke_geaendert).toBe(true);
  });
});

describe('Ausblenden', () => {
  it('Erfolg: Route gerufen, Band weg', async () => {
    vorbereiten();
    const f = vi.fn(async () => antwort(200, { ok: true }));
    vi.stubGlobal('fetch', f);
    expect(await markeHinweisAusblenden()).toBeNull();
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe('/m');
    expect(pultStore.getState().start?.marke_geaendert).toBe(false);
  });

  it('Fehler: Grund, Band bleibt', async () => {
    vorbereiten();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(503, { grund: 'Marketing gerade nicht erreichbar' })));
    expect(await markeHinweisAusblenden()).toBe('Marketing gerade nicht erreichbar');
    expect(pultStore.getState().start?.marke_geaendert).toBe(true);
  });

  it('auch Ausblenden ist gesperrt, solange der Agent arbeitet', async () => {
    vorbereiten({}, { chat: { laeuft: true, verlauf: [], live: null, neueste: null } });
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    expect(await markeHinweisAusblenden()).toBe('Der Assistent arbeitet gerade');
    expect(f).not.toHaveBeenCalled();
  });
});
