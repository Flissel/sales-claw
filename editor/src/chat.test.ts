import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  ChatEintrag,
  chatLaden,
  chatSenden,
  dateiNamen,
  exportieren,
  exportVorschau,
  exportVorschlag,
  neueFassungNachChat,
  rueckgaengig,
  rueckgaengigFuer,
  sperrText,
  titelSlug,
} from './chat';
import type { Start } from './pult';

const start = {
  chat_url: '/marketing/editor/abc/chat',
  chat_stand_url: '/marketing/editor/abc/chat.json',
  chat_rueckgaengig_url: '/marketing/editor/abc/chat/rueckgaengig',
  export_vorschau_url: '/marketing/editor/abc/export/vorschau',
  export_url: '/marketing/editor/abc/export',
  csrf: 'marke-1',
} as Start;

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function aufruf(f: ReturnType<typeof vi.fn>, n = 0): [string, RequestInit] {
  return f.mock.calls[n] as unknown as [string, RequestInit];
}

function eintrag(teil: Partial<ChatEintrag>): ChatEintrag {
  return {
    id: 'a1',
    art: 'chat',
    nachricht: 'Mach den Kopf ruhiger',
    antwort: '',
    status: 'offen',
    hinweise: [],
    ergebnis: {},
    fassung_vorher: 3,
    fassung_nachher: null,
    erstellt_am: '2026-10-02 12:00:00+00',
    ...teil,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe('chatSenden', () => {
  it('sendet POST mit X-CSRF und {nachricht, kontext} und liefert den Auftrag', async () => {
    const f = vi.fn(async () => antwort(200, { auftrag: 'c-1' }));
    vi.stubGlobal('fetch', f);
    const r = await chatSenden(start, 'Hallo', { fenster: 'flaeche:kopf', auswahl: 'titel' });
    expect(r).toEqual({ ok: true, auftrag: 'c-1' });
    const [adresse, init] = aufruf(f);
    expect(adresse).toBe('/marketing/editor/abc/chat');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
    expect(JSON.parse(String(init.body))).toEqual({
      nachricht: 'Hallo',
      kontext: { fenster: 'flaeche:kopf', auswahl: 'titel' },
    });
  });

  it('422: der Grund des Servers wird durchgereicht', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Der Assistent arbeitet gerade' })));
    expect(await chatSenden(start, 'x', { fenster: 'newsletter', auswahl: null })).toEqual({
      ok: false,
      grund: 'Der Assistent arbeitet gerade',
    });
  });

  it('Netzfehler: Keine Verbindung zum Pult', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    expect(await chatSenden(start, 'x', { fenster: 'newsletter', auswahl: null })).toEqual({
      ok: false,
      grund: 'Keine Verbindung zum Pult',
    });
  });

  it('200 ohne Auftrag ist ein Fehler', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, {})));
    const r = await chatSenden(start, 'x', { fenster: 'newsletter', auswahl: null });
    expect(r.ok).toBe(false);
  });
});

describe('chatLaden', () => {
  it('liest laeuft und den Verlauf, verwirft kaputte Eintraege', async () => {
    const gut = eintrag({ status: 'fertig', antwort: 'Erledigt', hinweise: ['Kontrast knapp'], fassung_nachher: 4 });
    const f = vi.fn(async () =>
      antwort(200, { laeuft: false, verlauf: [gut, { id: 7 }, { ...gut, id: 'a2', hinweise: null, ergebnis: null, antwort: null }] }),
    );
    vi.stubGlobal('fetch', f);
    const r = await chatLaden(start);
    expect(aufruf(f)[0]).toBe('/marketing/editor/abc/chat.json');
    expect(r?.laeuft).toBe(false);
    expect(r?.verlauf).toEqual([gut, { ...gut, id: 'a2', hinweise: [], ergebnis: {}, antwort: '' }]);
  });

  it('null bei Netzfehler', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    expect(await chatLaden(start)).toBeNull();
  });

  it('null bei 503 und bei unbrauchbarer Antwort', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(503, { grund: 'Assistent gerade nicht erreichbar' })));
    expect(await chatLaden(start)).toBeNull();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { verlauf: 'x' })));
    expect(await chatLaden(start)).toBeNull();
  });
});

describe('neueFassungNachChat', () => {
  it('erkennt in_arbeit -> fertig mit fassung_nachher', () => {
    const vorher = [eintrag({ status: 'in_arbeit' })];
    const nachher = [eintrag({ status: 'fertig', fassung_nachher: 4 })];
    expect(neueFassungNachChat(vorher, nachher)).toBe(4);
  });

  it('auch offen -> fertig (Arbeiter war schneller als die Abfrage)', () => {
    expect(neueFassungNachChat([eintrag({ status: 'offen' })], [eintrag({ status: 'fertig', fassung_nachher: 5 })])).toBe(5);
  });

  it('nichts bei fertig ohne Fassung, bei fehler und bei schon fertigen Eintraegen', () => {
    expect(neueFassungNachChat([eintrag({ status: 'in_arbeit' })], [eintrag({ status: 'fertig' })])).toBeNull();
    expect(neueFassungNachChat([eintrag({ status: 'in_arbeit' })], [eintrag({ status: 'fehler' })])).toBeNull();
    const fertig = eintrag({ status: 'fertig', fassung_nachher: 4 });
    expect(neueFassungNachChat([fertig], [fertig])).toBeNull();
  });

  it('beim ersten Laden (Eintrag vorher unbekannt) wird nicht geladen', () => {
    expect(neueFassungNachChat([], [eintrag({ status: 'fertig', fassung_nachher: 4 })])).toBeNull();
  });
});

describe('exportVorschlag', () => {
  it('liest ergebnis.export_vorschlag', () => {
    const e = eintrag({ status: 'fertig', ergebnis: { export_vorschlag: { newsletter: true, flaechen: ['kopf'] } } });
    expect(exportVorschlag(e)).toEqual({ newsletter: true, flaechen: ['kopf'] });
  });

  it('null ohne Vorschlag, bei null und bei kaputter Form', () => {
    expect(exportVorschlag(eintrag({}))).toBeNull();
    expect(exportVorschlag(eintrag({ ergebnis: { export_vorschlag: null } }))).toBeNull();
    const kaputt = eintrag({ ergebnis: { export_vorschlag: { newsletter: 'ja', flaechen: 3 } as never } });
    expect(exportVorschlag(kaputt)).toBeNull();
  });
});

describe('rueckgaengig', () => {
  it('sendet den Auftrag mit CSRF und liefert die neue Fassung', async () => {
    const f = vi.fn(async () => antwort(200, { fassung: 6 }));
    vi.stubGlobal('fetch', f);
    expect(await rueckgaengig(start, 'a1')).toEqual({ ok: true, fassung: 6 });
    const [adresse, init] = aufruf(f);
    expect(adresse).toBe('/marketing/editor/abc/chat/rueckgaengig');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
    expect(JSON.parse(String(init.body))).toEqual({ auftrag: 'a1' });
  });

  it('422 liefert den Grund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Dieser Auftrag hat nichts geändert' })));
    expect(await rueckgaengig(start, 'a1')).toEqual({ ok: false, grund: 'Dieser Auftrag hat nichts geändert' });
  });
});

describe('exportVorschau', () => {
  it('sendet die Flaechen und liest je Flaeche drei Geraete', async () => {
    const bilder = { handy: 'medien:gs-aaaaaaaaaaaa.jpg', tablet: 'medien:gs-bbbbbbbbbbbb.jpg', pc: 'medien:gs-cccccccccccc.jpg' };
    const f = vi.fn(async () => antwort(200, { flaechen: { kopf: bilder, kaputt: { handy: 3 } } }));
    vi.stubGlobal('fetch', f);
    expect(await exportVorschau(start, ['kopf'])).toEqual({ ok: true, flaechen: { kopf: bilder } });
    const [adresse, init] = aufruf(f);
    expect(adresse).toBe('/marketing/editor/abc/export/vorschau');
    expect(JSON.parse(String(init.body))).toEqual({ flaechen: ['kopf'] });
  });
});

describe('exportieren', () => {
  it('sendet bestaetigt: true mit der Auswahl', async () => {
    const f = vi.fn(async () => antwort(200, { dateien: ['herbst-kopf-handy.jpg'], auftrag: 'e-1' }));
    vi.stubGlobal('fetch', f);
    const r = await exportieren(start, { newsletter: true, flaechen: ['kopf'] });
    expect(r).toEqual({ ok: true, dateien: ['herbst-kopf-handy.jpg'], auftrag: 'e-1' });
    const [adresse, init] = aufruf(f);
    expect(adresse).toBe('/marketing/editor/abc/export');
    expect((init.headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
    expect(JSON.parse(String(init.body))).toEqual({ newsletter: true, flaechen: ['kopf'], bestaetigt: true });
  });

  it('ohne Newsletter: auftrag null', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { dateien: [], auftrag: null })));
    expect(await exportieren(start, { newsletter: false, flaechen: [] })).toEqual({ ok: true, dateien: [], auftrag: null });
  });

  it('422 liefert den Grund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'kopf ist keine Fläche' })));
    expect(await exportieren(start, { newsletter: false, flaechen: ['kopf'] })).toEqual({ ok: false, grund: 'kopf ist keine Fläche' });
  });
});

describe('Dateinamen', () => {
  it('titelSlug wie der Server (Umlaute, Sonderzeichen, Leer -> newsletter)', () => {
    expect(titelSlug('Oktober-Angebot für Größen!')).toBe('oktober-angebot-fuer-groessen');
    expect(titelSlug('  ')).toBe('newsletter');
    expect(titelSlug('x'.repeat(70))).toHaveLength(60);
  });

  it('dateiNamen: Newsletter je Geraet, Flaeche je Geraet', () => {
    expect(dateiNamen('herbst', { newsletter: true, flaechen: ['kopf'] })).toEqual([
      'herbst-handy.jpg',
      'herbst-tablet.jpg',
      'herbst-pc.jpg',
      'herbst-kopf-handy.jpg',
      'herbst-kopf-tablet.jpg',
      'herbst-kopf-pc.jpg',
    ]);
  });
});

describe('rueckgaengigFuer', () => {
  const alt = eintrag({ id: 'a1', status: 'fertig', fassung_vorher: 3, fassung_nachher: 4 });
  const neu = eintrag({ id: 'a2', status: 'fertig', fassung_vorher: 4, fassung_nachher: 5 });

  it('nur die neueste fertige Antwort, deren Fassung die aktuelle ist', () => {
    expect(rueckgaengigFuer([alt, neu], 5)).toBe('a2');
  });

  it('aeltere Antworten nie (Rueckgaengig verwuerfe die spaetere Arbeit)', () => {
    expect(rueckgaengigFuer([alt, neu], 4)).toBeNull();
  });

  it('nichts, wenn danach jemand gespeichert hat', () => {
    expect(rueckgaengigFuer([alt, neu], 6)).toBeNull();
  });

  it('Antworten ohne Fassung, Fehler und Exporte zaehlen nicht als neueste', () => {
    const ohne = eintrag({ id: 'a3', status: 'fertig', fassung_nachher: null });
    const fehl = eintrag({ id: 'a4', status: 'fehler' });
    const exp = eintrag({ id: 'e1', art: 'export', status: 'fertig', fassung_nachher: null });
    expect(rueckgaengigFuer([neu, ohne, fehl, exp], 5)).toBe('a2');
  });

  it('eine laufende neuere Nachricht sperrt nichts weg, aber laeuft wird extra gesperrt', () => {
    expect(rueckgaengigFuer([neu, eintrag({ id: 'a5', status: 'in_arbeit' })], 5)).toBe('a2');
  });
});

describe('sperrText', () => {
  it('null, solange nichts laeuft', () => {
    expect(sperrText(null)).toBeNull();
    expect(sperrText({ laeuft: false, verlauf: [] })).toBeNull();
  });

  it('Agent oder Newsletter-Export', () => {
    expect(sperrText({ laeuft: true, verlauf: [eintrag({ status: 'in_arbeit' })] })).toBe('Agent arbeitet …');
    expect(sperrText({ laeuft: true, verlauf: [eintrag({ art: 'export', status: 'offen' })] })).toBe('Newsletter-Bilder werden gerechnet …');
  });
});
