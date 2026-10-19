import { afterEach, describe, expect, it, vi } from 'vitest';

import { Start, vorlageAlsNeu, vorlageAnwenden, vorlagenListe } from './pult';

const IID = 'b12c46b9-8f87-412b-b2e7-7215b354a75b';
const start = {
  csrf: 'marke-1',
  speichern_url: `/marketing/editor/${IID}/speichern`,
  vorlagen_url: `/marketing/editor/${IID}/vorlagen.json`,
  vorlage_bild_url: `/marketing/editor/${IID}/vorlage-bild/`,
  vorlage_url: `/marketing/editor/${IID}/vorlage`,
} as Start;

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('vorlagenListe', () => {
  it('liest die Liste und filtert Einträge ohne Namen', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        antwort(200, {
          vorlagen: [
            { name: 'klassik', beschreibung: 'Ruhig und klar', fassung: 3 },
            { beschreibung: 'ohne Namen', fassung: 1 },
            { name: '', beschreibung: 'leer', fassung: 1 },
            { name: 'studio' },
            'quatsch',
          ],
        }),
      ),
    );
    expect(await vorlagenListe(start)).toEqual([
      { name: 'klassik', beschreibung: 'Ruhig und klar', fassung: 3 },
      { name: 'studio', beschreibung: '', fassung: 0 },
    ]);
  });

  it('fragt die Adresse aus dem Start ab', async () => {
    const f = vi.fn(async () => antwort(200, { vorlagen: [] }));
    vi.stubGlobal('fetch', f);
    await vorlagenListe(start);
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe(start.vorlagen_url);
  });

  it('503, Müll oder Netzfehler: null (nicht erreichbar)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(503, { grund: 'weg' })));
    expect(await vorlagenListe(start)).toBeNull();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>', { status: 200 })));
    expect(await vorlagenListe(start)).toBeNull();
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('x'))));
    expect(await vorlagenListe(start)).toBeNull();
  });

  it('ohne Adresse (älteres sales-ui): null ohne Anfrage', async () => {
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    expect(await vorlagenListe({ csrf: 'x' } as Start)).toBeNull();
    expect(f).not.toHaveBeenCalled();
  });
});

describe('vorlageAnwenden', () => {
  it('sendet X-CSRF, art "anwenden" und basis_fassung', async () => {
    const f = vi.fn(async () => antwort(200, { fassung: 8 }));
    vi.stubGlobal('fetch', f);
    expect(await vorlageAnwenden(start, 'klassik', 7)).toEqual({ ok: true, fassung: 8 });
    const [adresse, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(adresse).toBe(start.vorlage_url);
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
    expect(JSON.parse(String(init.body))).toEqual({ vorlage: 'klassik', art: 'anwenden', basis_fassung: 7 });
  });

  it('422 liefert den Grund (Assistent arbeitet, veraltete Basis)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Der Assistent arbeitet gerade' })));
    expect(await vorlageAnwenden(start, 'klassik', 7)).toEqual({
      ok: false,
      konflikt: false,
      grund: 'Der Assistent arbeitet gerade',
    });
  });

  it('Antwort ohne Fassung oder ohne Grund: Standardgrund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, {})));
    const r = await vorlageAnwenden(start, 'klassik', 7);
    expect(r.ok).toBe(false);
    vi.stubGlobal('fetch', vi.fn(async () => antwort(503, {})));
    expect(await vorlageAnwenden(start, 'klassik', 7)).toEqual({
      ok: false,
      konflikt: false,
      grund: 'Anwenden gerade nicht möglich',
    });
  });

  it('Netzfehler: Keine Verbindung zum Pult', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('x'))));
    expect(await vorlageAnwenden(start, 'klassik', 7)).toEqual({
      ok: false,
      konflikt: false,
      grund: 'Keine Verbindung zum Pult',
    });
  });

  it('ohne Adresse: nicht eingerichtet', async () => {
    const r = await vorlageAnwenden({ csrf: 'x' } as Start, 'klassik', 7);
    expect(r).toEqual({ ok: false, konflikt: false, grund: 'Vorlagen sind hier noch nicht eingerichtet' });
  });
});

describe('vorlageAlsNeu', () => {
  it('sendet art "neu" mit Titel und liefert editorUrl', async () => {
    const f = vi.fn(async () => antwort(200, { editor_url: '/marketing/editor/0b6c2c1e-7a39-4f5f-8a39-6a9f7d1c2b3e' }));
    vi.stubGlobal('fetch', f);
    expect(await vorlageAlsNeu(start, 'studio', 'Herbstpost')).toEqual({
      ok: true,
      editorUrl: '/marketing/editor/0b6c2c1e-7a39-4f5f-8a39-6a9f7d1c2b3e',
    });
    const [adresse, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(adresse).toBe(start.vorlage_url);
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
    expect(JSON.parse(String(init.body))).toEqual({ vorlage: 'studio', art: 'neu', titel: 'Herbstpost' });
  });

  it('editorUrl nur, wenn sie mit /marketing/editor/ beginnt', async () => {
    for (const fremd of ['https://boese.example/marketing/editor/x', '//boese.example/x', '/medien', 42, null]) {
      vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { editor_url: fremd })));
      const r = await vorlageAlsNeu(start, 'studio', 'Herbstpost');
      expect(r.ok).toBe(false);
    }
  });

  it('422 liefert den Grund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Unbekannte Vorlage' })));
    expect(await vorlageAlsNeu(start, 'studio', 'Herbstpost')).toEqual({ ok: false, grund: 'Unbekannte Vorlage' });
  });
});
