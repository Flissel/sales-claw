import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { anhangHochladen } from './chat';
import type { Start } from './pult';
import { FakeXhr } from './__fixtures__/fakeXhr';

const start = { anhang_url: '/marketing/editor/abc/anhang', csrf: 'marke-1' } as Start;

beforeEach(() => {
  FakeXhr.letzte = null;
  vi.stubGlobal('XMLHttpRequest', FakeXhr);
});

afterEach(() => vi.unstubAllGlobals());

const datei = () => new File([new Uint8Array(10)], 'Mein Foto.PNG', { type: 'image/png' });

describe('anhangHochladen', () => {
  it('POST multipart "datei" mit X-CSRF, meldet Fortschritt, liefert den gespeicherten Namen', async () => {
    const stufen: number[] = [];
    const p = anhangHochladen(start, datei(), (f) => stufen.push(f));
    const x = FakeXhr.letzte as FakeXhr;
    expect(x.methode).toBe('POST');
    expect(x.url).toBe('/marketing/editor/abc/anhang');
    expect(x.kopf['X-CSRF']).toBe('marke-1');
    expect(x.withCredentials).toBe(true);
    expect(x.body).toBeInstanceOf(FormData);
    expect(((x.body as FormData).get('datei') as File).name).toBe('Mein Foto.PNG');
    x.fortschritt(5, 10);
    x.fortschritt(10, 10);
    x.ende(200, { name: 'mein-foto.png', art: 'bild', groesse: 10 });
    expect(await p.promise).toEqual({ ok: true, name: 'mein-foto.png', art: 'bild', groesse: 10 });
    expect(stufen).toEqual([0.5, 1]);
  });

  it('Grund des Servers bei 422/413', async () => {
    const p = anhangHochladen(start, datei(), () => undefined);
    FakeXhr.letzte?.ende(422, { grund: 'Dateityp nicht erlaubt' });
    expect(await p.promise).toEqual({ ok: false, grund: 'Dateityp nicht erlaubt' });
    const q = anhangHochladen(start, datei(), () => undefined);
    FakeXhr.letzte?.ende(413, 'kein json');
    expect(await q.promise).toEqual({ ok: false, grund: expect.stringContaining('zu groß') });
  });

  it('Netzfehler, unverstaendliche Antwort, Abbruch', async () => {
    const p = anhangHochladen(start, datei(), () => undefined);
    FakeXhr.letzte?.onerror?.();
    expect(await p.promise).toEqual({ ok: false, grund: 'Keine Verbindung zum Pult' });
    const q = anhangHochladen(start, datei(), () => undefined);
    FakeXhr.letzte?.ende(200, { name: 'x.png', art: 'video' });
    expect(await q.promise).toEqual({ ok: false, grund: 'Antwort unverständlich' });
    const r = anhangHochladen(start, datei(), () => undefined);
    r.abbrechen();
    expect(FakeXhr.letzte?.abgebrochen).toBe(true);
    expect(await r.promise).toEqual({ ok: false, grund: 'Abgebrochen' });
  });

  it('ohne anhang_url (aelteres sales-ui): gar kein Aufruf', async () => {
    const p = anhangHochladen({ csrf: 'm' } as Start, datei(), () => undefined);
    expect(FakeXhr.letzte).toBeNull();
    expect(await p.promise).toEqual({ ok: false, grund: expect.stringContaining('nicht eingerichtet') });
  });
});
