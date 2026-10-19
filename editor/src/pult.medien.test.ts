import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  firmaEtikett,
  geloeschtText,
  inhaltId,
  LOESCHEN_OHNE_FIRMA,
  leereBildwahl,
  LoeschInfo,
  loeschFrage,
  MEDIEN_LEER,
  medienListe,
  medienLoeschen,
  medienZuordnen,
  Start,
} from './pult';
import { medienLaden, neueFassungNachBildLoeschen, pultStore } from './pultZustand';

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

describe('leereBildwahl', () => {
  it('zeigt den Zuordnungs-Hinweis statt "keine Bilder"', () => {
    expect(leereBildwahl(0, 'Bildzuordnung nicht erreichbar')).toBe('Bildzuordnung nicht erreichbar');
    expect(leereBildwahl(0, 'Bildzuordnung nicht erreichbar')).not.toBe(MEDIEN_LEER);
  });
  it('leere Bibliothek ohne Hinweis', () => {
    expect(leereBildwahl(0, null)).toBe(MEDIEN_LEER);
  });
  it('mit Bildern und ohne Hinweis kein Text', () => {
    expect(leereBildwahl(3, null)).toBeNull();
  });
});

describe('firmaEtikett', () => {
  it('Name der Firma', () => {
    expect(firmaEtikett({ id: 'laura', name: 'Laura Nails' })).toBe('Laura Nails');
    expect(firmaEtikett({ id: 'laura', name: '' })).toBe('laura');
  });
  it('kein Etikett ohne Firma oder mit leerer id', () => {
    expect(firmaEtikett(null)).toBeNull();
    expect(firmaEtikett(undefined)).toBeNull();
    expect(firmaEtikett({ id: '', name: '' })).toBeNull();
    expect(firmaEtikett({ id: '  ', name: 'X' })).toBeNull();
  });
});

const IID = 'b12c46b9-8f87-412b-b2e7-7215b354a75b';
const loeschStart = {
  csrf: 'marke-1',
  speichern_url: `/marketing/editor/${IID}/speichern`,
  stand_url: `/marketing/editor/${IID}/stand.json`,
  medien_loeschen_url: '/marketing/editor/medien/loeschen',
} as Start;

describe('medienLoeschen', () => {
  it('schickt die iid dieses Newsletters mit (sonst gilt still die Firma des Ladens)', async () => {
    expect(inhaltId(loeschStart)).toBe(IID);
    const f = vi.fn(async () => antwort(200, { name: 'a.png', entwuerfe: 0, sperre: null, umstellbar: 0, newsletter: [] }));
    vi.stubGlobal('fetch', f);
    await medienLoeschen(loeschStart, 'a.png', false);
    await medienLoeschen(loeschStart, 'a.png', true);
    for (const call of f.mock.calls as unknown as [string, RequestInit][]) {
      expect(call[0]).toBe('/marketing/editor/medien/loeschen');
      expect((call[1].headers as Record<string, string>)['X-CSRF']).toBe('marke-1');
      expect(JSON.parse(String(call[1].body)).iid).toBe(IID);
    }
    expect(JSON.parse(String((f.mock.calls[1] as unknown as [string, RequestInit])[1].body))).toEqual({
      name: 'a.png',
      bestaetigt: true,
      iid: IID,
    });
  });

  it('liest umstellbar und Newsletter mit umstellbar', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        antwort(200, {
          name: 'a.png',
          entwuerfe: 1,
          sperre: null,
          umstellbar: 2,
          newsletter: [
            { titel: 'Herbst', status: 'entwurf', umstellbar: true },
            { titel: 'Alt', status: 'freigegeben', umstellbar: false },
          ],
        }),
      ),
    );
    const r = await medienLoeschen(loeschStart, 'a.png', false);
    expect(r).toEqual({
      ok: true,
      umgestellt: [],
      info: {
        name: 'a.png',
        entwuerfe: 1,
        sperre: null,
        umstellbar: 2,
        newsletter: [
          { titel: 'Herbst', status: 'entwurf', umstellbar: true },
          { titel: 'Alt', status: 'freigegeben', umstellbar: false },
        ],
      },
    });
  });

  it('ältere Antwort ohne umstellbar: 0, kein Absturz', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => antwort(200, { name: 'a.png', entwuerfe: 0, sperre: null, newsletter: [{ titel: 'X', status: 'entwurf' }] })),
    );
    const r = await medienLoeschen(loeschStart, 'a.png', false);
    expect(r.ok && r.info?.umstellbar).toBe(0);
    expect(r.ok && r.info?.newsletter[0].umstellbar).toBe(false);
    expect(r.ok && r.info && loeschFrage(r.info)).toContain('Das lässt sich nicht rückgängig machen.');
  });

  it('Sperre wird unverändert durchgereicht', async () => {
    const sperre = 'Das Bild steckt im Newsletter „Herbst“, der zur Freigabe liegt – erst zurückziehen.';
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { name: 'a.png', entwuerfe: 0, sperre, umstellbar: 0, newsletter: [] })));
    const r = await medienLoeschen(loeschStart, 'a.png', false);
    expect(r.ok && r.info?.sperre).toBe(sperre);
  });

  it('bestätigt: umgestellte Entwürfe kommen mit', async () => {
    const umgestellt = [{ id: IID, titel: 'Herbst', fassung: 9 }];
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { geloescht: 'a.png', umgestellt })));
    expect(await medienLoeschen(loeschStart, 'a.png', true)).toEqual({ ok: true, info: null, umgestellt });
  });

  it('409 nennt den Grund und die schon umgestellten', async () => {
    const umgestellt = [{ id: 'x', titel: 'Herbst', fassung: 9 }];
    vi.stubGlobal('fetch', vi.fn(async () => antwort(409, { grund: 'Der Assistent arbeitet gerade', umgestellt })));
    expect(await medienLoeschen(loeschStart, 'a.png', true)).toEqual({ ok: false, grund: 'Der Assistent arbeitet gerade', umgestellt });
  });
});

describe('loeschFrage', () => {
  const info = (teil: Partial<LoeschInfo> = {}): LoeschInfo => ({
    name: 'a.png',
    entwuerfe: 0,
    sperre: null,
    umstellbar: 2,
    newsletter: [
      { titel: 'Herbst-Newsletter', status: 'entwurf', umstellbar: true },
      { titel: 'Einladung Hausmesse', status: 'entwurf', umstellbar: true },
      { titel: 'Längst verschickt', status: 'freigegeben', umstellbar: false },
    ],
    ...teil,
  });

  it('nennt die Zahl, beide Titel und den Platzhalter', () => {
    const t = loeschFrage(info());
    expect(t).toContain('„a.png“ endgültig aus den Medien löschen?');
    expect(t).toContain('in 2 Entwürfen verwendet');
    expect(t).toContain('Herbst-Newsletter');
    expect(t).toContain('Einladung Hausmesse');
    expect(t).not.toContain('Längst verschickt');
    expect(t).toContain('Platzhalter');
    expect(t.endsWith('Das lässt sich nicht rückgängig machen.')).toBe(true);
  });

  it('ein Entwurf in der Einzahl, Sales-Entwürfe dazu', () => {
    const t = loeschFrage(info({ umstellbar: 1, entwuerfe: 3, newsletter: [{ titel: 'Herbst', status: 'entwurf', umstellbar: true }] }));
    expect(t).toContain('in 1 Entwurf verwendet: Herbst.');
    expect(t).toContain('3 Sales-Entwurf/Entwürfe nennen diese Datei');
  });

  it('ohne umstellbare Entwürfe keine Platzhalter-Warnung', () => {
    expect(loeschFrage(info({ umstellbar: 0, newsletter: [] }))).not.toContain('Platzhalter');
  });
});

describe('neueFassungNachBildLoeschen', () => {
  function speicherFaelschen() {
    const speicher = new Map<string, string>();
    vi.stubGlobal('sessionStorage', {
      getItem: (k: string) => speicher.get(k) ?? null,
      setItem: (k: string, v: string) => void speicher.set(k, v),
      removeItem: (k: string) => void speicher.delete(k),
    });
    const reload = vi.fn();
    vi.stubGlobal('window', { location: { reload } });
    return { speicher, reload };
  }

  it('neuere Fassung, Ungespeichertes: Stand übernehmen (Band), kein Neuladen, kein Merkzettel', async () => {
    const { speicher, reload } = speicherFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { fassung: 9, auftraege: [] })));
    pultStore.setState({ start: loeschStart, basis: 8, ungespeichert: true, stand: null });
    expect(await neueFassungNachBildLoeschen('„a.png“ gelöscht.')).toBe(true);
    expect(pultStore.getState().stand?.fassung).toBe(9);
    expect(reload).not.toHaveBeenCalled();
    expect(speicher.get('vibemind-neues-bild')).toBeUndefined();
  });

  it('neuere Fassung ohne Ungespeichertes: lädt neu, die Meldung überlebt das Neuladen', async () => {
    const { speicher, reload } = speicherFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { fassung: 9, auftraege: [] })));
    pultStore.setState({ start: loeschStart, basis: 8, ungespeichert: false, hinweisOffen: false, gestaltungOffen: null, chatAnhaenge: [], stand: null });
    expect(await neueFassungNachBildLoeschen('„a.png“ gelöscht – 1 Entwurf zeigt jetzt einen Platzhalter.')).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(JSON.parse(speicher.get('vibemind-neues-bild') ?? '{}').text).toBe('„a.png“ gelöscht – 1 Entwurf zeigt jetzt einen Platzhalter.');
  });

  it('nurAnzeigen (Fehler im Dialog): Stand übernehmen, nie neu laden', async () => {
    const { reload } = speicherFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { fassung: 9, auftraege: [] })));
    pultStore.setState({ start: loeschStart, basis: 8, ungespeichert: false, stand: null });
    expect(await neueFassungNachBildLoeschen(null, true)).toBe(true);
    expect(pultStore.getState().stand?.fassung).toBe(9);
    expect(reload).not.toHaveBeenCalled();
  });

  it('keine neuere Fassung: nichts', async () => {
    speicherFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { fassung: 8, auftraege: [] })));
    pultStore.setState({ start: loeschStart, basis: 8, ungespeichert: true, stand: null });
    expect(await neueFassungNachBildLoeschen('x')).toBe(false);
  });
});

describe('medienLoeschen ohne Firma', () => {
  it('ohne iid wird nichts gesendet, Löschen ist gesperrt', async () => {
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    const ohne = { ...loeschStart, speichern_url: '/irgendwo/speichern' } as Start;
    expect(inhaltId(ohne)).toBeNull();
    expect(await medienLoeschen(ohne, 'a.png', false)).toEqual({ ok: false, grund: LOESCHEN_OHNE_FIRMA });
    expect(await medienLoeschen(ohne, 'a.png', true)).toEqual({ ok: false, grund: LOESCHEN_OHNE_FIRMA });
    expect(f).not.toHaveBeenCalled();
  });

  it('ein iid-Feld im Start geht vor', () => {
    expect(inhaltId({ ...loeschStart, iid: '0b6c2c1e-7a39-4f5f-8a39-6a9f7d1c2b3e' } as Start)).toBe('0b6c2c1e-7a39-4f5f-8a39-6a9f7d1c2b3e');
  });
});

describe('geloeschtText', () => {
  it('nennt die Entwürfe mit Platzhalter', () => {
    expect(geloeschtText('a.png', 0)).toBe('„a.png“ gelöscht.');
    expect(geloeschtText('a.png', 2)).toBe('„a.png“ gelöscht – 2 Entwürfe zeigen jetzt einen Platzhalter.');
    expect(geloeschtText('a.png', 1)).toBe('„a.png“ gelöscht – 1 Entwurf zeigt jetzt einen Platzhalter.');
    // Gezaehlt wird, was der Server umgestellt hat - nie die Vorhersage aus der Pruefung.
    expect(geloeschtText('a.png', [].length)).not.toContain('Platzhalter');
  });
});
