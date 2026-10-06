import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FakeXhr } from './__fixtures__/fakeXhr';
import type { ChatEintrag } from './chat';
import type { AnhangChip } from './chatKontext';
import { resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import {
  anhangEntfernen,
  anhangHinzu,
  auswahlEntfernen,
  blockAlsKontext,
  chatAbschicken,
  chatVormerken,
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
  root: { type: 'EmailLayout', data: { childrenIds: ['titel', 'bild'] } },
  titel: { type: 'Heading', data: { props: { text: 'Goldener Herbst' } } },
  bild: { type: 'Image', data: { props: { url: '/medien/datei/held.png' } } },
} as TEditorConfiguration;

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
