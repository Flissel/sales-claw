import { afterEach, describe, expect, it, vi } from 'vitest';

import { ABGEMELDET, aendern, einrichten, laden, loeschen } from './api';

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

  it('folgt keiner Umleitung (redirect manual)', async () => {
    const f = vi.fn(async () => antwort(200, '{"ereignisse":[]}'));
    vi.stubGlobal('fetch', f);
    await laden('a', 'b');
    expect((f.mock.calls[0] as unknown as [string, RequestInit])[1].redirect).toBe('manual');
  });

  it('abgelaufene Sitzung: umgeleitete HTML-Seite mit 200 ist ein Fehler, kein leerer Kalender', async () => {
    const r0 = antwort(200, '<html>Anmelden</html>', 'text/html');
    Object.defineProperty(r0, 'redirected', { value: true });
    vi.stubGlobal('fetch', vi.fn(async () => r0));
    const r = await laden('a', 'b');
    expect(r).toEqual({ ok: false, status: 200, daten: { grund: ABGEMELDET } });
    expect(ABGEMELDET).toBe('Abgemeldet – bitte neu anmelden');
  });

  it('abgelaufene Sitzung: 303 bzw. opaqueredirect wird zu Abgemeldet', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 303, headers: { location: '/login' } })));
    expect((await laden('a', 'b')).daten.grund).toBe(ABGEMELDET);
    const opak = new Response(null, { status: 200 });
    Object.defineProperty(opak, 'type', { value: 'opaqueredirect' });
    Object.defineProperty(opak, 'status', { value: 0 });
    Object.defineProperty(opak, 'ok', { value: false });
    vi.stubGlobal('fetch', vi.fn(async () => opak));
    const r = await laden('a', 'b');
    expect(r.ok).toBe(false);
    expect(r.daten.grund).toBe(ABGEMELDET);
  });

  it('200 ohne JSON ist ein Fehler', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, '<html></html>', 'text/html')));
    const r = await laden('a', 'b');
    expect(r.ok).toBe(false);
    expect(r.daten.grund).toBe(ABGEMELDET);
  });
});
