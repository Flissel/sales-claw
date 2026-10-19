import { afterEach, describe, expect, it, vi } from 'vitest';

import { fassungWiederherstellen, FassungInfo, Start } from './pult';
import {
  fassungZeile,
  verlaufVorschauUrl,
  wiederherstellenSichtbar,
  wiederherstellenSperre,
  wiederherstellenText,
} from './App/VerlaufMenue';

const IID = 'b12c46b9-8f87-412b-b2e7-7215b354a75b';
const start = {
  csrf: 'marke-1',
  vorschau_url: `/marketing/entwurf/${IID}/vorschau`,
  wiederherstellen_url: `/marketing/editor/${IID}/wiederherstellen`,
} as Start;

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('fassungWiederherstellen', () => {
  it('sendet {fassung, basis_fassung} mit X-CSRF', async () => {
    const f = vi.fn(async () => antwort(200, { fassung: 9 }));
    vi.stubGlobal('fetch', f);
    expect(await fassungWiederherstellen(start, 4, 8)).toEqual({ ok: true, fassung: 9 });
    const [adresse, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(adresse).toBe(start.wiederherstellen_url);
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
    expect(JSON.parse(String(init.body))).toEqual({ fassung: 4, basis_fassung: 8 });
  });

  it('fehlende wiederherstellen_url: nicht eingerichtet, keine Anfrage', async () => {
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    expect(await fassungWiederherstellen({ csrf: 'x' } as Start, 4, 8)).toMatchObject({
      ok: false,
      grund: 'Wiederherstellen ist hier noch nicht eingerichtet',
    });
    expect(f).not.toHaveBeenCalled();
  });

  it('422 liefert den Grund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Inzwischen gibt es Fassung 9' })));
    expect(await fassungWiederherstellen(start, 4, 8)).toMatchObject({ ok: false, grund: 'Inzwischen gibt es Fassung 9' });
  });

  it('Netzfehler: Keine Verbindung zum Pult', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('x'))));
    expect(await fassungWiederherstellen(start, 4, 8)).toMatchObject({ ok: false, grund: 'Keine Verbindung zum Pult' });
  });
});

const f = (fassung: number, teil: Partial<FassungInfo> = {}): FassungInfo => ({
  fassung,
  urheber: 'betreiber',
  erstellt_am: '2026-10-19T08:05:00Z',
  format: 'bloecke',
  ...teil,
});

describe('Verlauf-Menü', () => {
  it('Zeile: Fassung N · du|Agent · Datum', () => {
    expect(fassungZeile(f(4))).toMatch(/^Fassung 4 · du · 19\.10\. \d\d:05$/);
    expect(fassungZeile(f(5, { urheber: 'agent' }))).toMatch(/^Fassung 5 · Agent · /);
  });

  it('Ansehen öffnet die Pult-Vorschau der Fassung als Mail', () => {
    expect(verlaufVorschauUrl(start, 4)).toBe(`/marketing/entwurf/${IID}/vorschau?fassung=4&format=mail`);
    expect(verlaufVorschauUrl({ vorschau_url: '/v?x=1' } as Start, 4)).toBe('/v?x=1&fassung=4&format=mail');
  });

  it('Wiederherstellen erscheint für alle älteren Fassungen, nie für die neueste', () => {
    expect(wiederherstellenSichtbar(f(4), 8)).toBe(true);
    expect(wiederherstellenSichtbar(f(4, { format: 'felder' }), 8)).toBe(true);
    expect(wiederherstellenSichtbar(f(8), 8)).toBe(false);
  });

  it('gesperrt mit Grund: altes Format, ungespeichert, nurLesen, Agent', () => {
    const frei = { ungespeichert: false, nurLesen: false, agent: null };
    expect(wiederherstellenSperre(f(4), frei)).toBeNull();
    expect(wiederherstellenSperre(f(4, { format: 'felder' }), frei)).toBe('Altes Format – lässt sich hier nicht wiederherstellen');
    expect(wiederherstellenSperre(f(4), { ...frei, ungespeichert: true })).toBe('Erst speichern');
    expect(wiederherstellenSperre(f(4), { ...frei, nurLesen: true })).toBe('Liegt zur Freigabe – erst zurückziehen');
    expect(wiederherstellenSperre(f(4), { ...frei, agent: 'Agent arbeitet …' })).toBe('Gesperrt, bis der Assistent fertig ist');
  });

  it('Bestätigungstext', () => {
    expect(wiederherstellenText(4, 8)).toBe(
      'Fassung 4 als neue Fassung wiederherstellen? Deine jetzige Fassung 8 bleibt im Verlauf.',
    );
  });
});
