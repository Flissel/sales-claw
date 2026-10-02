import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChatEintrag } from './chat';
import { resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import { CHAT_TAKT_MS, chatAbfragen, chatAbschicken, chatRueckgaengig, pultStore } from './pultZustand';

const START = {
  speichern_url: '/s',
  chat_url: '/c',
  chat_stand_url: '/c.json',
  chat_rueckgaengig_url: '/c/r',
  csrf: 'm',
} as Start;

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

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

// Antworten je Adresse, der Reihe nach (die letzte wiederholt sich).
function netz(antworten: Record<string, Array<[number, unknown]>>) {
  const f = vi.fn(async (url: string) => {
    const liste = antworten[url];
    if (!liste) throw new TypeError('unbekannt ' + url);
    const [status, body] = liste.length > 1 ? (liste.shift() as [number, unknown]) : liste[0];
    return antwort(status, body);
  });
  vi.stubGlobal('fetch', f);
  return f;
}

const adressen = (f: ReturnType<typeof netz>) => f.mock.calls.map((c) => c[0]);

let reload: ReturnType<typeof vi.fn>;
let speicher: Map<string, string>;

beforeEach(() => {
  vi.useFakeTimers();
  reload = vi.fn();
  speicher = new Map();
  vi.stubGlobal('window', { location: { reload } });
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => speicher.get(k) ?? null,
    setItem: (k: string, v: string) => void speicher.set(k, v),
    removeItem: (k: string) => void speicher.delete(k),
  });
  resetDocument({ root: { type: 'EmailLayout', data: { childrenIds: [] } } } as TEditorConfiguration);
  pultStore.setState({ start: START, basis: 3, ungespeichert: false, hinweisOffen: false, gestaltungOffen: null, gestaltungGeaendert: false, chat: null });
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('chatAbfragen', () => {
  it('fragt einmal und hoert auf, wenn nichts laeuft', async () => {
    const f = netz({ '/c.json': [[200, { laeuft: false, verlauf: [] }]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS * 3);
    expect(adressen(f)).toEqual(['/c.json']);
    expect(pultStore.getState().chat).toEqual({ laeuft: false, verlauf: [] });
  });

  it('fragt alle 2 s, solange laeuft, und laedt bei fertiger neuer Fassung neu', async () => {
    const f = netz({
      '/c.json': [
        [200, { laeuft: true, verlauf: [eintrag({})] }],
        [200, { laeuft: true, verlauf: [eintrag({})] }],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fertig', fassung_nachher: 4 })] }],
      ],
    });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    expect(pultStore.getState().chat?.laeuft).toBe(true);
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS * 2);
    expect(adressen(f)).toEqual(['/c.json', '/c.json', '/c.json']);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(speicher.get('vibemind-neu-geladen')).toBe('4');
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS * 3);
    expect(f).toHaveBeenCalledTimes(3);
  });

  it('kein Neuladen bei ungespeicherten Aenderungen oder schon einmal geladener Fassung', async () => {
    netz({
      '/c.json': [
        [200, { laeuft: true, verlauf: [eintrag({})] }],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fertig', fassung_nachher: 4 })] }],
      ],
    });
    speicher.set('vibemind-neu-geladen', '4');
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS);
    expect(reload).not.toHaveBeenCalled();
  });

  it('offenes, unveraendertes Gestaltungsfenster: neu laden und Fenster merken', async () => {
    resetDocument({
      root: { type: 'EmailLayout', data: { childrenIds: ['kopf'] } },
      kopf: { type: 'Image', data: { props: { url: null } } },
    } as TEditorConfiguration);
    pultStore.setState({ gestaltungOffen: 'kopf', gestaltungGeaendert: false });
    netz({
      '/c.json': [
        [200, { laeuft: true, verlauf: [eintrag({})] }],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fertig', fassung_nachher: 4 })] }],
      ],
    });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(speicher.get('vibemind-fenster')).toBe('kopf');
  });
});

describe('chatAbschicken', () => {
  it('speichert Ungesichertes zuerst, sperrt sofort und fragt den Stand ab', async () => {
    pultStore.setState({ ungespeichert: true });
    const f = netz({
      '/s': [[200, { fassung: 4 }]],
      '/c': [[200, { auftrag: 'neu-1' }]],
      '/c.json': [[200, { laeuft: true, verlauf: [eintrag({ id: 'neu-1', status: 'offen', fassung_vorher: 4 })] }]],
    });
    const p = chatAbschicken('Mach es ruhiger', { fenster: 'newsletter', auswahl: null });
    await vi.advanceTimersByTimeAsync(0);
    expect(await p).toBeNull();
    expect(adressen(f).slice(0, 3)).toEqual(['/s', '/c', '/c.json']);
    expect(pultStore.getState()).toMatchObject({ basis: 4, ungespeichert: false });
    expect(pultStore.getState().chat?.laeuft).toBe(true);
    expect(pultStore.getState().chat?.verlauf.map((e) => e.id)).toEqual(['neu-1']);
  });

  it('Speichern scheitert: nichts wird gesendet, Grund kommt zurueck', async () => {
    pultStore.setState({ ungespeichert: true });
    const f = netz({ '/s': [[422, { grund: 'Der Assistent arbeitet gerade' }]] });
    const grund = await chatAbschicken('x', { fenster: 'newsletter', auswahl: null });
    expect(grund).toContain('Der Assistent arbeitet gerade');
    expect(adressen(f)).toEqual(['/s']);
  });

  it('waehrend der Agent arbeitet wird nichts gesendet', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [] } });
    const f = netz({});
    expect(await chatAbschicken('x', { fenster: 'newsletter', auswahl: null })).toBe('Der Assistent arbeitet gerade');
    expect(f).not.toHaveBeenCalled();
  });
});

describe('chatRueckgaengig', () => {
  it('legt die vorige Fassung neu an und laedt neu', async () => {
    const f = netz({ '/c/r': [[200, { fassung: 6 }]] });
    expect(await chatRueckgaengig('a1')).toBeNull();
    expect(JSON.parse(String((f.mock.calls[0] as unknown as [string, RequestInit])[1].body))).toEqual({ auftrag: 'a1' });
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('mit ungespeicherten Aenderungen gesperrt', async () => {
    pultStore.setState({ ungespeichert: true });
    const f = netz({});
    expect(await chatRueckgaengig('a1')).toMatch(/Erst speichern/);
    expect(f).not.toHaveBeenCalled();
  });
});
