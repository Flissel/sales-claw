import { afterEach, describe, expect, it, vi } from 'vitest';

import { aendern, einrichten, laden, loeschen } from './api';

function antwort(status: number, koerper: string, typ = 'application/json') {
  return new Response(koerper, { status, headers: { 'content-type': typ } });
}

afterEach(() => vi.unstubAllGlobals());

describe('api', () => {
  it('schreibt mit x-csrf und same-origin', async () => {
    const f = vi.fn(async () => antwort(200, '{"ereignis":{}}'));
    vi.stubGlobal('fetch', f);
    einrichten('MARKE');
    const r = await aendern('kunde:a b', { dauer_minuten: 30 });
    expect(r).toEqual({ ok: true, status: 200, daten: { ereignis: {} } });
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/kalender/termine/kunde%3Aa%20b');
    expect(init.method).toBe('PATCH');
    expect(init.credentials).toBe('same-origin');
    expect((init.headers as Record<string, string>)['x-csrf']).toBe('MARKE');
    expect(init.body).toBe('{"dauer_minuten":30}');
  });

  it('laden kodiert von/bis', async () => {
    const f = vi.fn(async () => antwort(200, '{"ereignisse":[],"hinweise":[]}'));
    vi.stubGlobal('fetch', f);
    await laden('2026-10-19T00:00:00+02:00', '2026-10-26T00:00:00+01:00');
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe(
      '/kalender/termine.json?von=2026-10-19T00%3A00%3A00%2B02%3A00&bis=2026-10-26T00%3A00%3A00%2B01%3A00');
  });

  it('HTML-403 der Anmeldewache wird zu "Keine Berechtigung"', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(403, '<html>nein</html>', 'text/html')));
    const r = await loeschen('eigen:x', {});
    expect(r).toEqual({ ok: false, status: 403, daten: { grund: 'Keine Berechtigung' } });
  });

  it('Netzfehler wird zu Status 0', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline'); }));
    const r = await laden('a', 'b');
    expect(r.ok).toBe(false);
    expect(r.status).toBe(0);
    expect(r.daten.grund).toMatch(/nicht erreichbar/);
  });

  it('JSON-Fehler behaelt grund und Zusatzfelder', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(409, '{"grund":"Konflikt","konflikte":[],"unvollstaendig":true}')));
    const r = await aendern('eigen:x', {});
    expect(r).toEqual({ ok: false, status: 409, daten: { grund: 'Konflikt', konflikte: [], unvollstaendig: true } });
  });
});
