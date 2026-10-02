import { afterEach, describe, expect, it, vi } from 'vitest';

import { neueGestaltung } from './gestaltung';
import { gestaltungRechnen, Start } from './pult';

const start = {
  gestaltung_url: '/marketing/editor/abc/gestaltung',
  csrf: 'marke-1',
} as Start;
const g = neueGestaltung('#FFFFFF');

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('gestaltungRechnen', () => {
  it('sendet POST mit X-CSRF und {gestaltung} und liefert das Serverbild', async () => {
    const f = vi.fn(async () =>
      antwort(200, { url: 'medien:gs-aaaaaaaaaaaa.jpg', width: 600, height: 400, hinweise: ['x'] }),
    );
    vi.stubGlobal('fetch', f);
    const r = await gestaltungRechnen(start, g);
    expect(r).toEqual({ ok: true, url: 'medien:gs-aaaaaaaaaaaa.jpg', width: 600, height: 400, hinweise: ['x'] });
    expect(f).toHaveBeenCalledTimes(1);
    const [adresse, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(adresse).toBe('/marketing/editor/abc/gestaltung');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
    expect(JSON.parse(String(init.body))).toEqual({ gestaltung: g });
  });

  it('422 liefert den Grund des Servers', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Bild x fehlt in den Medien' })));
    expect(await gestaltungRechnen(start, g)).toEqual({ ok: false, grund: 'Bild x fehlt in den Medien' });
  });

  it('Netzfehler: Keine Verbindung zum Pult', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    expect(await gestaltungRechnen(start, g)).toEqual({ ok: false, grund: 'Keine Verbindung zum Pult' });
  });

  it('200 ohne brauchbare Antwort ist ein Fehler', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { url: 42 })));
    const r = await gestaltungRechnen(start, g);
    expect(r.ok).toBe(false);
  });
});
