import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  ChatEintrag,
  chatLaden,
  chatSenden,
  dateiNamen,
  laufenderChat,
  exportieren,
  exportVorschau,
  exportVorschlag,
  neueFassungNachChat,
  rueckgaengig,
  rueckgaengigFuer,
  sperrText,
  stoppDialogOffen,
  stoppen,
  titelSlug,
} from './chat';
import type { Start } from './pult';

const start = {
  chat_url: '/marketing/editor/abc/chat',
  chat_stand_url: '/marketing/editor/abc/chat.json',
  chat_rueckgaengig_url: '/marketing/editor/abc/chat/rueckgaengig',
  export_vorschau_url: '/marketing/editor/abc/export/vorschau',
  export_url: '/marketing/editor/abc/export',
  chat_stopp_url: '/marketing/editor/abc/chat/stopp',
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
    denken: '',
    schritte: [],
    schritt: '',
    schritt_nr: 0,
    stopp: null,
    bild_hinweise: [],
    ...teil,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe('chatSenden', () => {
  it('sendet POST mit X-CSRF und {nachricht, kontext} und liefert Auftrag und Status', async () => {
    const f = vi.fn(async () => antwort(200, { auftrag: 'a-1', status: 'wartet' }));
    vi.stubGlobal('fetch', f);
    const r = await chatSenden(start, 'Hallo', { fenster: 'flaeche:kopf', auswahl: 'titel' });
    expect(r).toEqual({ ok: true, auftrag: 'a-1', status: 'wartet' });
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { auftrag: 'a-2' })));
    expect(await chatSenden(start, 'x', { fenster: 'newsletter', auswahl: null })).toEqual({ ok: true, auftrag: 'a-2', status: 'offen' });
    vi.stubGlobal('fetch', f);
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
    expect(r?.live).toBeNull();
    expect(r?.neueste).toBeNull();
  });

  it('liest live, neueste_fassung und die Felder laufender und wartender Runden', async () => {
    const roh = { ...eintrag({ id: 'w', status: 'wartet' }), schritt: 'Titel', schritt_nr: 2, stopp: 'behalten',
      bild_hinweise: ['Bild für held nicht erzeugt: weg', 5] };
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { laeuft: true, verlauf: [roh], live: null, neueste_fassung: 7 })));
    const r = await chatLaden(start);
    expect(r?.neueste).toBe(7);
    expect(r?.verlauf[0]).toMatchObject({ status: 'wartet', schritt: 'Titel', schritt_nr: 2, stopp: 'behalten',
      bild_hinweise: ['Bild für held nicht erzeugt: weg'] });
  });

  it('kaputtes live wird vorsichtig gelesen', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        antwort(200, {
          laeuft: true,
          verlauf: [],
          live: { schritt: 5, schritt_nr: 'x', zwischenstand: [1], stopp: 'egal' },
        }),
      ),
    );
    const r = await chatLaden(start);
    expect(r?.live).toEqual({ schritt: '', schritt_nr: 0, zwischenstand: null, stopp: null, denken: '', schritte: [] });
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
  const f = (id: string, nachher: number | null, teil: Partial<ChatEintrag> = {}) =>
    eintrag({ id, status: 'fertig', fassung_nachher: nachher, ...teil });
  it('die Runde, deren Fassung die neueste ist - auch wenn danach eine Runde ohne Fassung fertig wurde', () => {
    expect(rueckgaengigFuer([f('a', 5), f('b', 6), f('c', null)], 6)).toBe('b');
  });
  it('parallel: eine aeltere Runde, die zuletzt gespeichert hat', () => {
    expect(rueckgaengigFuer([f('spaet', 7), f('frueh', 6)], 7)).toBe('spaet');
    expect(rueckgaengigFuer([f('spaet', 7), f('frueh', 6)], 6)).toBe('frueh');
  });
  it('nichts, wenn die neueste Fassung von niemandem aus dem Chat ist oder unbekannt', () => {
    expect(rueckgaengigFuer([f('a', 5)], 6)).toBeNull();
    expect(rueckgaengigFuer([f('a', 5)], null)).toBeNull();
  });
  it('Fehler und Exporte zaehlen nicht', () => {
    expect(rueckgaengigFuer([f('x', 5, { status: 'fehler' }), f('e', 5, { art: 'export' })], 5)).toBeNull();
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

describe('laufenderChat', () => {
  it('der offene oder laufende Chat-Auftrag, nie ein Export', () => {
    expect(laufenderChat(null)).toBeNull();
    expect(laufenderChat({ laeuft: true, verlauf: [eintrag({ id: 'x', art: 'export', status: 'in_arbeit' })] })).toBeNull();
    expect(laufenderChat({ laeuft: false, verlauf: [eintrag({ status: 'fertig' })] })).toBeNull();
    expect(laufenderChat({ laeuft: true, verlauf: [eintrag({ id: 'f', status: 'fertig' }), eintrag({ id: 'l', status: 'in_arbeit' })] })?.id).toBe('l');
  });
});

describe('stoppDialogOffen', () => {
  const lauf = (id: string) => ({ laeuft: true, verlauf: [eintrag({ id, status: 'in_arbeit' })] });
  it('nur fuer den Lauf, fuer den er geoeffnet wurde', () => {
    expect(stoppDialogOffen('a1', lauf('a1'))).toBe(true);
    expect(stoppDialogOffen(null, lauf('a1'))).toBe(false);
  });
  it('Lauf zu Ende oder ein neuer Lauf: der Dialog geht nicht von selbst (wieder) auf', () => {
    expect(stoppDialogOffen('a1', { laeuft: false, verlauf: [eintrag({ status: 'fertig' })] })).toBe(false);
    expect(stoppDialogOffen('a1', lauf('a2'))).toBe(false);
  });
});

describe('Stopp', () => {
  it('stoppen: POST {art, auftrag} an chat_stopp_url, liest abgeschlossen und veraltet', async () => {
    const f = vi.fn(async () => antwort(200, { abgeschlossen: false }));
    vi.stubGlobal('fetch', f);
    expect(await stoppen(start, 'behalten', 'a1')).toEqual({ ok: true, abgeschlossen: false, veraltet: false });
    const [adresse, init] = aufruf(f);
    expect(adresse).toBe('/marketing/editor/abc/chat/stopp');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ art: 'behalten', auftrag: 'a1' });
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { abgeschlossen: false, veraltet: true })));
    expect(await stoppen(start, 'verwerfen')).toEqual({ ok: true, abgeschlossen: false, veraltet: true });
  });

  it('stoppen ohne Auftrag schickt nur die Art', async () => {
    const f = vi.fn(async () => antwort(200, { abgeschlossen: true }));
    vi.stubGlobal('fetch', f);
    await stoppen(start, 'verwerfen');
    expect(JSON.parse(String(aufruf(f)[1].body))).toEqual({ art: 'verwerfen' });
  });
});
