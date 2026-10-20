import { afterEach, describe, expect, it, vi } from 'vitest';

import { pruefungLaden, type Start } from './pult';

const IID = 'b12c46b9-8f87-412b-b2e7-7215b354a75b';
const start = { csrf: 'marke-1', pruefung_url: `/marketing/editor/${IID}/pruefung` } as Start;

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('pruefungLaden', () => {
  it('fragt die Fassung ab (GET, ohne CSRF) und liest nur saubere Befunde', async () => {
    const f = vi.fn(async () =>
      antwort(200, {
        befunde: [
          { schwere: 'hart', punkt: 'titel', satz: 'titel: Kontrast 2,1:1 auf dem Bild – mindestens 3:1' },
          { schwere: 'weich', punkt: 'seite', satz: 'Kein Knopf' },
          { schwere: 'laut', punkt: 'x', satz: 'y' },
          { schwere: 'hart', punkt: 4, satz: 'z' },
          { schwere: 'weich', punkt: 'a', satz: '' },
          'quatsch',
        ],
      }),
    );
    vi.stubGlobal('fetch', f);
    expect(await pruefungLaden(start, 7)).toEqual({
      ok: true,
      befunde: [
        { schwere: 'hart', punkt: 'titel', satz: 'titel: Kontrast 2,1:1 auf dem Bild – mindestens 3:1' },
        { schwere: 'weich', punkt: 'seite', satz: 'Kein Knopf' },
      ],
    });
    const [adresse, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(adresse).toBe(`/marketing/editor/${IID}/pruefung?fassung=7`);
    expect(init.method).toBeUndefined();
    expect(init.headers).toBeUndefined();
  });

  it('ohne Fassung: die neueste', async () => {
    const f = vi.fn(async () => antwort(200, { befunde: [] }));
    vi.stubGlobal('fetch', f);
    expect(await pruefungLaden(start)).toEqual({ ok: true, befunde: [] });
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe(`/marketing/editor/${IID}/pruefung`);
  });

  it('422/503 liefern den Grund, Müll und Netzfehler einen Standardgrund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Das ist keine Collage' })));
    expect(await pruefungLaden(start, 2)).toEqual({ ok: false, grund: 'Das ist keine Collage' });
    vi.stubGlobal('fetch', vi.fn(async () => antwort(503, {})));
    expect(await pruefungLaden(start, 2)).toEqual({ ok: false, grund: 'Prüfung gerade nicht möglich' });
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { befunde: 'x' })));
    expect(await pruefungLaden(start, 2)).toEqual({ ok: false, grund: 'Antwort unverständlich' });
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('x'))));
    expect(await pruefungLaden(start, 2)).toEqual({ ok: false, grund: 'Keine Verbindung zum Pult' });
  });

  it('ohne Adresse (älteres sales-ui): nicht eingerichtet, keine Anfrage', async () => {
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    expect(await pruefungLaden({ csrf: 'x' } as Start, 1)).toEqual({ ok: false, grund: 'Prüfen ist hier noch nicht eingerichtet' });
    expect(f).not.toHaveBeenCalled();
  });
});
