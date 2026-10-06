import { afterEach, describe, expect, it, vi } from 'vitest';

import { medienListe, medienZuordnen, Start } from './pult';
import { medienLaden, pultStore } from './pultZustand';

const start = {
  medien_url: '/marketing/editor/medien.json?iid=abc',
  medien_zuordnung_url: '/marketing/editor/abc/medien/zuordnung',
  csrf: 'marke-1',
} as Start;

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const NEU = {
  bilder: ['a.png', 'b.jpg'],
  zuordnung: { 'a.png': 'acme', 'b.jpg': null },
  mandanten: [
    { id: 'vibemind', name: 'VibeMind' },
    { id: 'acme', name: 'Acme' },
  ],
  mandant: 'acme',
  hinweis: null,
};

afterEach(() => vi.unstubAllGlobals());

describe('medienListe', () => {
  it('liest das neue Format', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, NEU)));
    expect(await medienListe(start)).toEqual(NEU);
  });

  it('liest das alte Format {bilder} mit leerer Zuordnung', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { bilder: ['a.png'] })));
    expect(await medienListe(start)).toEqual({
      bilder: ['a.png'],
      zuordnung: {},
      mandanten: [],
      mandant: '',
      hinweis: null,
    });
  });

  it('500 liefert keine Bilder und einen Hinweis', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(500, {})));
    const r = await medienListe(start);
    expect(r.bilder).toEqual([]);
    expect(r.hinweis).toBe('Bildzuordnung nicht erreichbar');
  });

  it('Muell liefert keine Bilder und einen Hinweis', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>', { status: 200 })));
    const r = await medienListe(start);
    expect(r.bilder).toEqual([]);
    expect(r.hinweis).toBe('Bildzuordnung nicht erreichbar');
  });

  it('Netzfehler liefert keine Bilder und einen Hinweis', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('x'))));
    const r = await medienListe(start);
    expect(r.bilder).toEqual([]);
    expect(r.hinweis).toBe('Bildzuordnung nicht erreichbar');
  });

  it('uebernimmt den Hinweis des Servers', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { ...NEU, bilder: [], hinweis: 'Bildzuordnung nicht erreichbar' })));
    expect((await medienListe(start)).hinweis).toBe('Bildzuordnung nicht erreichbar');
  });
});

describe('medienZuordnen', () => {
  it('sendet {name, mandant} mit X-CSRF', async () => {
    const f = vi.fn(async () => antwort(200, { ok: true }));
    vi.stubGlobal('fetch', f);
    expect(await medienZuordnen(start, 'a.png', 'acme')).toEqual({ ok: true });
    const [adresse, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(adresse).toBe('/marketing/editor/abc/medien/zuordnung');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
    expect(JSON.parse(String(init.body))).toEqual({ name: 'a.png', mandant: 'acme' });
  });

  it('Gemeinsam bleibt null', async () => {
    const f = vi.fn(async () => antwort(200, { ok: true }));
    vi.stubGlobal('fetch', f);
    await medienZuordnen(start, 'a.png', null);
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(init.body)).toBe('{"name":"a.png","mandant":null}');
  });

  it('503 liefert den Grund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(503, { grund: 'Zuordnung gerade nicht möglich' })));
    expect(await medienZuordnen(start, 'a.png', null)).toEqual({ ok: false, grund: 'Zuordnung gerade nicht möglich' });
  });

  it('Netzfehler: Keine Verbindung zum Pult', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('x'))));
    expect(await medienZuordnen(start, 'a.png', null)).toEqual({ ok: false, grund: 'Keine Verbindung zum Pult' });
  });

  it('ohne Adresse: nicht eingerichtet', async () => {
    const r = await medienZuordnen({ csrf: 'x' } as Start, 'a.png', null);
    expect(r.ok).toBe(false);
  });
});

describe('medienLaden', () => {
  it('fuellt medienZuordnung, mandanten und medienHinweis', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, NEU)));
    pultStore.setState({ start });
    medienLaden(true);
    await vi.waitFor(() => expect(pultStore.getState().medien).toEqual(['a.png', 'b.jpg']));
    const z = pultStore.getState();
    expect(z.medienZuordnung).toEqual(NEU.zuordnung);
    expect(z.mandanten).toEqual(NEU.mandanten);
    expect(z.medienHinweis).toBeNull();
  });

  it('setzt den Hinweis bei Ausfall', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(500, {})));
    pultStore.setState({ start });
    medienLaden(true);
    await vi.waitFor(() => expect(pultStore.getState().medienHinweis).toBe('Bildzuordnung nicht erreichbar'));
    expect(pultStore.getState().medien).toEqual([]);
  });
});
