import { afterEach, describe, expect, it, vi } from 'vitest';

import { resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import { einreichen, fehlerText, speichern, Start, zurueckziehen } from './pult';
import { einreichenAuftrag, pultStarten, pultStore } from './pultZustand';

const DOK = {
  root: { type: 'EmailLayout', data: { childrenIds: [] } },
} as TEditorConfiguration;

function start(teil: Partial<Start> = {}): Start {
  return {
    dokument: DOK,
    betreff: 'B',
    vorschautext: 'V',
    basis_fassung: 2,
    speichern_url: '/s',
    einreichen_url: '/e',
    zurueckziehen_url: '/z',
    csrf: 'marke',
    ...teil,
  } as Start;
}

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('einreichen / zurueckziehen', () => {
  it('einreichen: POST mit X-CSRF an einreichen_url, ok bei 200', async () => {
    const f = vi.fn(async () => antwort(200, { status: 'eingereicht', fassung: 2 }));
    vi.stubGlobal('fetch', f);
    expect(await einreichen(start())).toEqual({ ok: true });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/e');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke');
  });

  it('einreichen: Grund des Servers kommt zurueck', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Ein Bild wird gerade erzeugt' })));
    expect(await einreichen(start())).toEqual({ ok: false, grund: 'Ein Bild wird gerade erzeugt' });
  });

  it('einreichen: kein Netz und fehlende Adresse', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('x'))));
    expect(await einreichen(start())).toEqual({ ok: false, grund: 'Keine Verbindung zum Pult' });
    expect((await einreichen(start({ einreichen_url: undefined }))).ok).toBe(false);
  });

  it('zurueckziehen: POST an zurueckziehen_url, Fehlergrund', async () => {
    const f = vi.fn(async () => antwort(200, { status: 'entwurf' }));
    vi.stubGlobal('fetch', f);
    expect(await zurueckziehen(start())).toEqual({ ok: true });
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe('/z');
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Schon entschieden (freigegeben)' })));
    expect(await zurueckziehen(start())).toEqual({ ok: false, grund: 'Schon entschieden (freigegeben)' });
  });
});

describe('Store nurLesen', () => {
  it('kommt aus dem Start-Status', () => {
    pultStarten(start({ status: 'eingereicht', eingereicht_am: '2026-10-07T09:30:00+00:00' }));
    expect(pultStore.getState().nurLesen).toBe(true);
    pultStarten(start({ status: 'entwurf' }));
    expect(pultStore.getState().nurLesen).toBe(false);
    pultStarten(start({ status: undefined }));
    expect(pultStore.getState().nurLesen).toBe(false);
  });
});

describe('einreichenAuftrag', () => {
  function vorbereiten(teil: Partial<ReturnType<typeof pultStore.getState>> = {}) {
    resetDocument(DOK);
    pultStarten(start());
    pultStore.setState({ chat: null, ...teil });
  }

  it('gesperrt, solange der Agent arbeitet: kein Netzaufruf', async () => {
    vorbereiten({ chat: { laeuft: true, verlauf: [], live: null, vorgemerkt: null } });
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    expect(await einreichenAuftrag()).toBe('Der Assistent arbeitet gerade');
    expect(f).not.toHaveBeenCalled();
    expect(pultStore.getState().nurLesen).toBe(false);
  });

  it('Erfolg: nurLesen und eingereicht_am gesetzt', async () => {
    vorbereiten();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { status: 'eingereicht', fassung: 2 })));
    expect(await einreichenAuftrag()).toBeNull();
    expect(pultStore.getState().nurLesen).toBe(true);
    expect(pultStore.getState().start?.eingereicht_am).toBeTruthy();
  });

  it('eingereicht_am kommt vom Server, wenn er es mitschickt', async () => {
    vorbereiten();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { status: 'eingereicht', fassung: 2, eingereicht_am: '2026-10-07T08:00:00+00:00' })));
    expect(await einreichenAuftrag()).toBeNull();
    expect(pultStore.getState().start?.eingereicht_am).toBe('2026-10-07T08:00:00+00:00');
  });

  it('Export am PC sperrt wie der Agent', async () => {
    vorbereiten({ chat: { laeuft: true, verlauf: [{ art: 'export', status: 'offen' } as never], live: null, vorgemerkt: null } });
    vi.stubGlobal('fetch', vi.fn());
    expect(await einreichenAuftrag()).toBe('Der Assistent arbeitet gerade');
  });

  it('speichert Ungespeichertes vorher; scheitert das, wird nicht eingereicht', async () => {
    vorbereiten();
    pultStore.setState({ ungespeichert: true });
    const f = vi.fn(async (url: string) =>
      url === '/s' ? antwort(422, { grund: 'Blocktyp Html ist nicht erlaubt' }) : antwort(200, {}),
    );
    vi.stubGlobal('fetch', f);
    const g = await einreichenAuftrag();
    expect(g).toBe(fehlerText('Blocktyp Html ist nicht erlaubt'));
    expect(f.mock.calls.map((c) => (c as unknown as [string])[0])).toEqual(['/s']);
    expect(pultStore.getState().nurLesen).toBe(false);
  });

  it('Server-Grund beim Einreichen bleibt, nurLesen bleibt aus', async () => {
    vorbereiten();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Ein Bild wird gerade erzeugt' })));
    expect(await einreichenAuftrag()).toBe('Ein Bild wird gerade erzeugt');
    expect(pultStore.getState().nurLesen).toBe(false);
  });
});

describe('Speichern bei eingereicht (Review Focus 5)', () => {
  it('Ablehnung zeigt den Grund und das Dokument bleibt', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Liegt zur Freigabe – erst zurückziehen' })));
    const e = await speichern(start(), DOK, 'B', 'V', 2, false);
    expect(e).toEqual({ ok: false, konflikt: false, grund: 'Liegt zur Freigabe – erst zurückziehen' });
    expect(fehlerText(e.ok ? '' : e.grund)).toBe(
      'Nicht gespeichert: Liegt zur Freigabe – erst zurückziehen. Deine Änderungen sind noch da.',
    );
  });
});
