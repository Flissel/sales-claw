import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FakeXhr } from './__fixtures__/fakeXhr';
import type { ChatEintrag } from './chat';
import type { AnhangChip } from './chatKontext';
import { onDocumentChange, resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import {
  anhangEntfernen,
  anhangHinzu,
  auswahlEntfernen,
  blockAlsKontext,
  chatAbfragen,
  chatAbschicken,
  chatVormerken,
  chipsAbgleichen,
  ebeneAlsKontext,
  pultStore,
  vorgemerkteChipsZurueck,
} from './pultZustand';

const START = {
  speichern_url: '/s',
  chat_url: '/c',
  chat_stand_url: '/c.json',
  chat_vormerkung_url: '/v',
  anhang_url: '/anhang',
  csrf: 'm',
} as Start;

const DOK = {
  root: { type: 'EmailLayout', data: { childrenIds: ['titel', 'bild', 'fl'] } },
  titel: { type: 'Heading', data: { props: { text: 'Goldener Herbst' } } },
  bild: { type: 'Image', data: { props: { url: '/medien/datei/held.png' } } },
  fl: { type: 'Image', data: { props: { url: '/medien/datei/fl.png', gestaltung: { ebenen: [{ id: 'e-1', art: 'text', text: 'Hallo' }] } } } },
} as unknown as TEditorConfiguration;

function eintrag(teil: Partial<ChatEintrag>): ChatEintrag {
  return {
    id: 'a1',
    art: 'chat',
    nachricht: 'n',
    antwort: '',
    status: 'in_arbeit',
    hinweise: [],
    ergebnis: {},
    fassung_vorher: 3,
    fassung_nachher: null,
    erstellt_am: 't',
    denken: '',
    schritte: [],
    ...teil,
  };
}

function netz(antworten: Record<string, [number, unknown]>) {
  const f = vi.fn(async (url: string, _init?: RequestInit) => {
    const a = antworten[url];
    if (!a) throw new TypeError('unbekannt ' + url);
    return new Response(JSON.stringify(a[1]), { status: a[0], headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', f);
  return f;
}
const body = (f: ReturnType<typeof netz>, url: string) => JSON.parse(String((f.mock.calls.find((c) => c[0] === url)?.[1] as RequestInit).body));

const fertig = (name: string, art: AnhangChip['art'] = 'bild'): AnhangChip => ({ id: 'k-' + name, name, art, status: 'fertig', fortschritt: 1 });
const bild = (name = 'foto.png', groesse = 10) => new File([new Uint8Array(groesse)], name, { type: 'image/png' });

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('window', { location: { reload: vi.fn() } });
  vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  FakeXhr.letzte = null;
  vi.stubGlobal('XMLHttpRequest', FakeXhr);
  resetDocument(DOK);
  pultStore.setState({
    start: START,
    basis: 3,
    ungespeichert: false,
    hinweisOffen: false,
    gestaltungOffen: null,
    chat: { laeuft: false, verlauf: [], live: null, vorgemerkt: null },
    chatAuswahl: [],
    chatAnhaenge: [],
    vorgemerktChips: null,
    chatHinweis: null,
    zwischenstand: null,
  });
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Kontext-Chips', () => {
  it('Block und Ebene als Chip, mit Kurztext; doppelt bleibt einer', () => {
    expect(blockAlsKontext('titel')).toBeNull();
    expect(blockAlsKontext('titel')).toBeNull();
    expect(ebeneAlsKontext('bild', { id: 'e-1', art: 'text', text: 'Neu im Oktober' } as never)).toBeNull();
    expect(pultStore.getState().chatAuswahl).toEqual([
      { art: 'block', id: 'titel', kurz: 'Überschrift · Goldener Herbst' },
      { art: 'ebene', id: 'e-1', flaeche: 'bild', kurz: 'Text-Ebene · Neu im Oktober' },
    ]);
    auswahlEntfernen(pultStore.getState().chatAuswahl[0]);
    expect(pultStore.getState().chatAuswahl.map((c) => c.id)).toEqual(['e-1']);
  });

  it('unbekannter Block: kein Chip; neunter Chip: Grund', () => {
    expect(blockAlsKontext('gibtsnicht')).not.toBeNull();
    pultStore.setState({ chatAuswahl: Array.from({ length: 8 }, (_, i) => ({ art: 'block' as const, id: 'b' + i, kurz: 'k' })) });
    expect(blockAlsKontext('titel')).toContain('8');
    expect(pultStore.getState().chatAuswahl).toHaveLength(8);
  });
});

describe('Senden mit Chips', () => {
  it('chatAbschicken schickt kontext.auswahl und kontext.anhaenge und leert die Chips', async () => {
    blockAlsKontext('titel');
    pultStore.setState({ chatAnhaenge: [fertig('foto.png'), fertig('preise.pdf', 'dokument')] });
    const f = netz({ '/c': [200, { auftrag: 'a9' }], '/c.json': [200, { laeuft: true, verlauf: [eintrag({ id: 'a9' })] }] });
    expect(await chatAbschicken('mach das kürzer', { fenster: 'newsletter', auswahl: 'bild' })).toBeNull();
    expect(body(f, '/c')).toEqual({
      nachricht: 'mach das kürzer',
      kontext: {
        fenster: 'newsletter',
        auswahl: [{ art: 'block', id: 'titel', kurz: 'Überschrift · Goldener Herbst' }],
        anhaenge: [
          { name: 'foto.png', art: 'bild' },
          { name: 'preise.pdf', art: 'dokument' },
        ],
      },
    });
    expect(pultStore.getState().chatAuswahl).toEqual([]);
    expect(pultStore.getState().chatAnhaenge).toEqual([]);
  });

  it('ohne Chips bleibt der Kontext wie bisher (einzelne Auswahl)', async () => {
    const f = netz({ '/c': [200, { auftrag: 'a9' }], '/c.json': [200, { laeuft: true, verlauf: [eintrag({ id: 'a9' })] }] });
    expect(await chatAbschicken('hallo', { fenster: 'newsletter', auswahl: 'bild' })).toBeNull();
    expect(body(f, '/c').kontext).toEqual({ fenster: 'newsletter', auswahl: 'bild' });
  });

  it('nur Anhaenge: auswahl bleibt die einzelne Auswahl', async () => {
    pultStore.setState({ chatAnhaenge: [fertig('foto.png')] });
    const f = netz({ '/c': [200, { auftrag: 'a9' }], '/c.json': [200, { laeuft: true, verlauf: [eintrag({ id: 'a9' })] }] });
    expect(await chatAbschicken('setz das ein', { fenster: 'newsletter', auswahl: null })).toBeNull();
    expect(body(f, '/c').kontext).toEqual({ fenster: 'newsletter', auswahl: null, anhaenge: [{ name: 'foto.png', art: 'bild' }] });
  });

  it('solange ein Upload laeuft: kein Senden', async () => {
    pultStore.setState({ chatAnhaenge: [{ ...fertig('foto.png'), status: 'laedt', fortschritt: 0.3 }] });
    const f = netz({});
    expect(await chatAbschicken('x', { fenster: 'newsletter', auswahl: null })).toContain('Anhänge');
    expect(f).not.toHaveBeenCalled();
  });

  it('Fehler beim Senden: Chips bleiben stehen', async () => {
    blockAlsKontext('titel');
    netz({ '/c': [503, { grund: 'Der Assistent ist gerade nicht erreichbar' }], '/c.json': [200, { laeuft: false, verlauf: [] }] });
    expect(await chatAbschicken('x', { fenster: 'newsletter', auswahl: null })).toBe('Der Assistent ist gerade nicht erreichbar');
    expect(pultStore.getState().chatAuswahl).toHaveLength(1);
  });

  it('Vormerken nimmt die Chips mit; die Karte kennt sie, Bearbeiten holt sie zurueck', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({})], live: null, vorgemerkt: null } });
    blockAlsKontext('titel');
    pultStore.setState({ chatAnhaenge: [fertig('foto.png')] });
    const f = netz({ '/v': [200, { id: 'v-1', status: 'wartet' }] });
    expect(await chatVormerken('danach kürzer', { fenster: 'newsletter', auswahl: null })).toBeNull();
    expect(body(f, '/v').kontext).toEqual({
      fenster: 'newsletter',
      auswahl: [{ art: 'block', id: 'titel', kurz: 'Überschrift · Goldener Herbst' }],
      anhaenge: [{ name: 'foto.png', art: 'bild' }],
    });
    const s = pultStore.getState();
    expect(s.chatAuswahl).toEqual([]);
    expect(s.chatAnhaenge).toEqual([]);
    expect(s.vorgemerktChips?.id).toBe('v-1');
    expect(s.vorgemerktChips?.auswahl).toHaveLength(1);
    expect(s.vorgemerktChips?.anhaenge).toHaveLength(1);
    vorgemerkteChipsZurueck();
    expect(pultStore.getState().chatAuswahl).toHaveLength(1);
    expect(pultStore.getState().chatAnhaenge.map((a) => a.name)).toEqual(['foto.png']);
  });

  it('Chips, die waehrend des Sendens dazukommen, bleiben fuer die naechste Nachricht', async () => {
    blockAlsKontext('titel');
    let fertigMelden: (r: Response) => void = () => undefined;
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url === '/c'
          ? new Promise<Response>((r) => (fertigMelden = r))
          : Promise.resolve(new Response(JSON.stringify({ laeuft: true, verlauf: [] }), { status: 200 })),
      ),
    );
    const p = chatAbschicken('x', { fenster: 'newsletter', auswahl: null });
    await vi.advanceTimersByTimeAsync(0);
    blockAlsKontext('bild');
    fertigMelden(new Response(JSON.stringify({ auftrag: 'a9' }), { status: 200 }));
    expect(await p).toBeNull();
    expect(pultStore.getState().chatAuswahl.map((c) => c.id)).toEqual(['bild']);
  });
});

describe('Anhaenge hochladen', () => {
  it('Chip sofort mit Fortschritt, danach fertig mit dem gespeicherten Namen', async () => {
    expect(anhangHinzu(bild('Mein Foto.png'))).toBeNull();
    let [a] = pultStore.getState().chatAnhaenge;
    expect(a).toMatchObject({ name: 'Mein Foto.png', art: 'bild', status: 'laedt', fortschritt: 0 });
    const x = FakeXhr.letzte as FakeXhr;
    x.fortschritt(3, 10);
    expect(pultStore.getState().chatAnhaenge[0].fortschritt).toBeCloseTo(0.3);
    x.ende(200, { name: 'mein-foto.png', art: 'bild', groesse: 10 });
    await vi.advanceTimersByTimeAsync(0);
    [a] = pultStore.getState().chatAnhaenge;
    expect(a).toMatchObject({ name: 'mein-foto.png', status: 'fertig', fortschritt: 1 });
  });

  it('Fehler vom Server und falscher Typ stehen am Chip, ohne Upload bei falschem Typ', async () => {
    anhangHinzu(bild());
    FakeXhr.letzte?.ende(422, { grund: 'Datei ist zu groß' });
    await vi.advanceTimersByTimeAsync(0);
    expect(pultStore.getState().chatAnhaenge[0]).toMatchObject({ status: 'fehler', grund: 'Datei ist zu groß' });
    FakeXhr.letzte = null;
    anhangHinzu(new File(['x'], 'film.mov'));
    expect(FakeXhr.letzte).toBeNull();
    expect(pultStore.getState().chatAnhaenge[1]).toMatchObject({ status: 'fehler', grund: expect.stringContaining('Typ') });
  });

  it('hoechstens 5 (fehlerhafte zaehlen nicht); Entfernen bricht einen laufenden Upload ab', () => {
    pultStore.setState({ chatAnhaenge: [...['a', 'b', 'c', 'd'].map((n) => fertig(n + '.png')), { ...fertig('x.png'), status: 'fehler' }] });
    expect(anhangHinzu(bild())).toBeNull();
    const x = FakeXhr.letzte as FakeXhr;
    expect(anhangHinzu(bild())).toContain('5');
    expect(pultStore.getState().chatAnhaenge).toHaveLength(6);
    const laufend = pultStore.getState().chatAnhaenge[5];
    anhangEntfernen(laufend.id);
    expect(x.abgebrochen).toBe(true);
    expect(pultStore.getState().chatAnhaenge.map((a) => a.id)).not.toContain(laufend.id);
  });
});

describe('Chips folgen dem aktuellen Dokument', () => {
  const ohne = (id: string) => {
    const d = { ...DOK } as Record<string, unknown>;
    delete d[id];
    d.root = { type: 'EmailLayout', data: { childrenIds: Object.keys(d).filter((k) => k !== 'root') } };
    return d as TEditorConfiguration;
  };
  const ohneEbene = (d: TEditorConfiguration = DOK) =>
    ({ ...d, fl: { type: 'Image', data: { props: { url: '/medien/datei/fl.png', gestaltung: { ebenen: [] } } } } }) as unknown as TEditorConfiguration;

  it('Senden laesst geloeschte Bloecke und Ebenen weg und sagt es', async () => {
    blockAlsKontext('titel');
    blockAlsKontext('bild');
    ebeneAlsKontext('fl', { id: 'e-1', art: 'text', text: 'Hallo' } as never);
    // Inzwischen (Agent, Rueckgaengig) ohne "bild" und ohne die Ebene - hier ohne Abgleich-Abo.
    resetDocument(ohneEbene(ohne('bild')));
    const f = netz({ '/c': [200, { auftrag: 'a9' }], '/c.json': [200, { laeuft: true, verlauf: [eintrag({ id: 'a9' })] }] });
    expect(await chatAbschicken('mach das kürzer', { fenster: 'newsletter', auswahl: null })).toBeNull();
    expect(body(f, '/c').kontext.auswahl).toEqual([{ art: 'block', id: 'titel', kurz: 'Überschrift · Goldener Herbst' }]);
    expect(pultStore.getState().chatHinweis).toBe('2 markierte Elemente gibt es nicht mehr – entfernt');
  });

  it('nur noch entfernte Chips: Kontext wie ohne Chips', async () => {
    blockAlsKontext('bild');
    resetDocument(ohne('bild'));
    const f = netz({ '/c': [200, { auftrag: 'a9' }], '/c.json': [200, { laeuft: true, verlauf: [eintrag({ id: 'a9' })] }] });
    expect(await chatAbschicken('x', { fenster: 'newsletter', auswahl: 'titel' })).toBeNull();
    expect(body(f, '/c').kontext).toEqual({ fenster: 'newsletter', auswahl: 'titel' });
    expect(pultStore.getState().chatHinweis).toBe('1 markiertes Element gibt es nicht mehr – entfernt');
  });

  it('Vormerken ebenso', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({})], live: null, vorgemerkt: null } });
    blockAlsKontext('titel');
    blockAlsKontext('bild');
    resetDocument(ohne('bild'));
    const f = netz({ '/v': [200, { id: 'v-1', status: 'wartet' }] });
    expect(await chatVormerken('danach', { fenster: 'newsletter', auswahl: null })).toBeNull();
    expect(body(f, '/v').kontext.auswahl.map((a: { id: string }) => a.id)).toEqual(['titel']);
    expect(pultStore.getState().vorgemerktChips?.auswahl.map((a) => a.id)).toEqual(['titel']);
  });

  it('beim Ersetzen des Dokuments verschwinden die Chips sofort, mit Hinweis', () => {
    const ab = onDocumentChange(chipsAbgleichen);
    try {
      blockAlsKontext('titel');
      blockAlsKontext('bild');
      ebeneAlsKontext('fl', { id: 'e-1', art: 'text', text: 'Hallo' } as never);
      resetDocument(ohneEbene());
      expect(pultStore.getState().chatAuswahl.map((c) => c.id)).toEqual(['titel', 'bild']);
      expect(pultStore.getState().chatHinweis).toBe('1 markiertes Element gibt es nicht mehr – entfernt');
      resetDocument(ohne('bild'));
      expect(pultStore.getState().chatAuswahl.map((c) => c.id)).toEqual(['titel']);
    } finally {
      ab();
    }
  });

  it('nicht waehrend ein Zwischenstand gezeigt wird - das echte Dokument kommt zurueck', () => {
    const ab = onDocumentChange(chipsAbgleichen);
    try {
      blockAlsKontext('bild');
      pultStore.setState({ zwischenstand: { echt: DOK, stand: {}, leuchtet: null, puls: 1 } });
      resetDocument(ohne('bild'));
      expect(pultStore.getState().chatAuswahl).toHaveLength(1);
    } finally {
      ab();
    }
  });

  it('die offene Flaeche wird beim Abgleich nicht geprueft - das Fenster haelt ungesicherte Ebenen', () => {
    const ab = onDocumentChange(chipsAbgleichen);
    try {
      pultStore.setState({ gestaltungOffen: 'fl' });
      ebeneAlsKontext('fl', { id: 'e-neu', art: 'text', text: 'Neu' } as never);
      resetDocument({ ...DOK });
      expect(pultStore.getState().chatAuswahl.map((c) => c.id)).toEqual(['e-neu']);
    } finally {
      ab();
    }
  });
});

describe('Hinweise am Eingabefeld', () => {
  it('abgelehnter Chip nennt den Grund, ein angenommener nimmt ihn weg', () => {
    expect(blockAlsKontext('gibtsnicht')).toBe('Diesen Block gibt es nicht mehr');
    expect(pultStore.getState().chatHinweis).toBe('Diesen Block gibt es nicht mehr');
    pultStore.setState({ chatAuswahl: Array.from({ length: 8 }, (_, i) => ({ art: 'block' as const, id: 'b' + i, kurz: 'k' })) });
    blockAlsKontext('titel');
    expect(pultStore.getState().chatHinweis).toContain('Höchstens 8');
    pultStore.setState({ chatAuswahl: [] });
    blockAlsKontext('titel');
    expect(pultStore.getState().chatHinweis).toBeNull();
  });
});

describe('Vormerkung verbraucht', () => {
  const merk = { id: 'v-1', auswahl: [{ art: 'block' as const, id: 'titel', kurz: 'k' }], anhaenge: [] };

  it('die vorgemerkte Nachricht startet - ihre id im Verlauf: vorgemerktChips weg', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({})], live: null, vorgemerkt: { id: 'v-1', nachricht: 'n' } }, vorgemerktChips: merk });
    netz({ '/c.json': [200, { laeuft: true, verlauf: [eintrag({ status: 'fertig' }), eintrag({ id: 'v-1', status: 'offen' })], vorgemerkt: null }] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    expect(pultStore.getState().vorgemerktChips).toBeNull();
    vorgemerkteChipsZurueck();
    expect(pultStore.getState().chatAuswahl).toEqual([]);
  });

  it('verspaetete Abfrage ohne Vormerkung: bleibt; ersetzt durch eine andere: weg', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({})], live: null, vorgemerkt: { id: 'v-1', nachricht: 'n' } }, vorgemerktChips: merk });
    netz({ '/c.json': [200, { laeuft: true, verlauf: [eintrag({})], vorgemerkt: null }] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    expect(pultStore.getState().vorgemerktChips?.id).toBe('v-1');
    netz({ '/c.json': [200, { laeuft: true, verlauf: [eintrag({})], vorgemerkt: { id: 'v-2', nachricht: 'anders' } }] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    expect(pultStore.getState().vorgemerktChips).toBeNull();
  });

  it('Bearbeiten holt nur zurueck, solange genau diese Vormerkung dasteht', () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({})], live: null, vorgemerkt: null }, vorgemerktChips: merk });
    vorgemerkteChipsZurueck();
    expect(pultStore.getState().chatAuswahl).toEqual([]);
  });
});
