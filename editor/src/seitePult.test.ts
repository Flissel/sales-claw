import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Start } from './pult';
import type { Seite } from './seite';
import { seiteSpeichern } from './seitePult';

const IID = 'b12c46b9-8f87-412b-b2e7-7215b354a75b';
const start = { csrf: 'marke-1', speichern_url: `/marketing/editor/${IID}/seite` } as Start;
const seite: Seite = {
  version: 1, breite: 600, hoehe: 800, hintergrund: { farbe: '#ffffff', bild: null },
  schriften: { anzeige: 'dm-sans', text: 'dm-sans' },
  ebenen: [{ id: 'f', art: 'form', form: 'rechteck', farbe: '#000000', x: 300, y: 200, breite: 100, hoehe: 50 }],
};

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('seiteSpeichern', () => {
  it('200 mit Fassung = gespeichert', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { fassung: 4 })));
    expect(await seiteSpeichern(start, seite, 'B', 'V', 3, false)).toEqual({ ok: true, fassung: 4 });
  });

  it('409 = Konflikt', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(409, { konflikt: true, grund: 'neuer' })));
    expect(await seiteSpeichern(start, seite, 'B', 'V', 3, false)).toEqual({ ok: false, konflikt: true });
  });

  it('422 = Grund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'X' })));
    expect(await seiteSpeichern(start, seite, 'B', 'V', 3, false)).toEqual({ ok: false, grund: 'X' });
  });

  it('503 ohne Grund und Netzfehler geben einen deutschen Grund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(503, {})));
    expect(await seiteSpeichern(start, seite, 'B', 'V', 3, false)).toEqual({ ok: false, grund: 'Speichern gerade nicht möglich' });
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('weg');
    }));
    expect(await seiteSpeichern(start, seite, 'B', 'V', 3, false)).toEqual({ ok: false, grund: 'Keine Verbindung zum Pult' });
  });

  it('schickt X-CSRF und einen Body mit seite, basis_fassung und als_kopie an speichern_url', async () => {
    const f = vi.fn(async (_url: string, _init: RequestInit) => antwort(200, { fassung: 5 }));
    vi.stubGlobal('fetch', f);
    await seiteSpeichern(start, seite, 'Betreff', 'Vorschau', 4, true);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe(`/marketing/editor/${IID}/seite`);
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
    const body: unknown = JSON.parse(String(init.body));
    expect(body).toEqual({ basis_fassung: 4, seite, betreff: 'Betreff', vorschautext: 'Vorschau', als_kopie: true });
  });
});
