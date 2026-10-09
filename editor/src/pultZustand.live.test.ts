import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChatEintrag } from './chat';
import { getDocument, onDocumentChange, resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import {
  alsUngespeichert,
  CHAT_TAKT_MS,
  chatAbfragen,
  EXPORT_TAKT_MS,
  chatStoppen,
  newsletterSichern,
  pultStore,
} from './pultZustand';

const START = {
  speichern_url: '/s',
  chat_url: '/c',
  chat_stand_url: '/c.json',
  chat_rueckgaengig_url: '/c/r',
  chat_stopp_url: '/stopp',
  csrf: 'm',
} as Start;

const ECHT = {
  root: { type: 'EmailLayout', data: { childrenIds: ['titel', 'bild'] } },
  titel: { type: 'Heading', data: { props: { text: 'Hallo' } } },
  bild: { type: 'Image', data: { props: { url: '/medien/datei/a.png' } } },
} as TEditorConfiguration;

// Zwischenstand im gespeicherten Format (medien:), Titel geaendert.
const ZWISCHEN_1 = {
  root: { type: 'EmailLayout', data: { childrenIds: ['titel', 'bild'] } },
  titel: { type: 'Heading', data: { props: { text: 'Neu' } } },
  bild: { type: 'Image', data: { props: { url: 'medien:a.png' } } },
};
// Danach zusaetzlich das Bild geaendert.
const ZWISCHEN_2 = { ...ZWISCHEN_1, bild: { type: 'Image', data: { props: { url: 'medien:b.png' } } } };

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
    denken: '',
    schritte: [],
    schritt: '',
    schritt_nr: 0,
    stopp: null,
    bild_hinweise: [],
    ...teil,
  };
}

const live = (zwischenstand: unknown, schritt_nr = 1, stopp: string | null = null) => ({
  schritt: 'Titel setzen',
  schritt_nr,
  zwischenstand,
  stopp,
});
const laeuft = (zwischenstand: unknown, nr = 1) => ({ laeuft: true, verlauf: [eintrag({})], live: live(zwischenstand, nr), neueste: null });

// Antworten je Adresse, der Reihe nach (die letzte wiederholt sich).
function netz(antworten: Record<string, Array<[number, unknown]>>) {
  const f = vi.fn(async (url: string, _init?: RequestInit) => {
    const liste = antworten[url];
    if (!liste) throw new TypeError('unbekannt ' + url);
    const [status, body] = liste.length > 1 ? (liste.shift() as [number, unknown]) : liste[0];
    return antwort(status, body);
  });
  vi.stubGlobal('fetch', f);
  return f;
}

const adressen = (f: ReturnType<typeof netz>) => f.mock.calls.map((c) => c[0]);
const aufruf = (f: ReturnType<typeof netz>, url: string) => f.mock.calls.find((c) => c[0] === url)?.[1] as RequestInit;

let reload: ReturnType<typeof vi.fn>;
let abmelden: () => void;

beforeEach(() => {
  vi.useFakeTimers();
  reload = vi.fn();
  const speicher = new Map<string, string>();
  vi.stubGlobal('window', { location: { reload } });
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => speicher.get(k) ?? null,
    setItem: (k: string, v: string) => void speicher.set(k, v),
    removeItem: (k: string) => void speicher.delete(k),
  });
  pultStore.setState({
    start: START,
    basis: 3,
    ungespeichert: false,
    hinweisOffen: false,
    gestaltungOffen: null,
    gestaltungGeaendert: false,
    chat: null,
    zwischenstand: null,
  });
  resetDocument(ECHT);
  // Wie main.tsx: jede Dokumentaenderung meldet "ungespeichert".
  abmelden = onDocumentChange(alsUngespeichert);
});

afterEach(() => {
  abmelden();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Takt', () => {
  it('fragt im Lauf jede Sekunde, danach nicht mehr', async () => {
    expect(CHAT_TAKT_MS).toBe(1000);
    const f = netz({
      '/c.json': [
        [200, laeuft(null, 0)],
        [200, laeuft(null, 0)],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fehler' })], live: null, neueste: null }],
      ],
    });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    expect(f).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(f).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1000);
    expect(f).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(5000);
    expect(adressen(f)).toEqual(['/c.json', '/c.json', '/c.json']);
  });
});

describe('Takt bei Export', () => {
  it('ein Newsletter-Export fragt weiter alle 2 s, nicht jede Sekunde', async () => {
    expect(EXPORT_TAKT_MS).toBe(2000);
    const exp = { laeuft: true, verlauf: [eintrag({ id: 'x1', art: 'export' })], live: null, neueste: null };
    const f = netz({ '/c.json': [[200, exp]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(f).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(f).toHaveBeenCalledTimes(2);
  });
});

describe('Zwischenstand im Canvas', () => {
  it('wird angezeigt (Medien als Anzeige-Adresse), zaehlt nie als ungespeichert und laesst sich nicht speichern', async () => {
    const f = netz({ '/c.json': [[200, laeuft(ZWISCHEN_1)]], '/s': [[200, { fassung: 9 }]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    expect(getDocument().titel).toEqual({ type: 'Heading', data: { props: { text: 'Neu' } } });
    expect(getDocument().bild).toEqual({ type: 'Image', data: { props: { url: '/medien/datei/a.png' } } });
    expect(pultStore.getState().ungespeichert).toBe(false);
    expect(pultStore.getState().zwischenstand?.leuchtet).toBe('titel');
    const e = await newsletterSichern(false);
    expect(e.ok).toBe(false);
    expect(adressen(f)).not.toContain('/s');
  });

  it('naechster Schritt: der zuletzt geaenderte Block leuchtet; gleicher Stand aendert nichts', async () => {
    netz({ '/c.json': [[200, laeuft(ZWISCHEN_1)], [200, laeuft(ZWISCHEN_2, 2)], [200, laeuft(ZWISCHEN_2, 2)]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    const puls1 = pultStore.getState().zwischenstand?.puls;
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS);
    const z = pultStore.getState().zwischenstand;
    expect(z?.leuchtet).toBe('bild');
    expect(z?.puls).not.toBe(puls1);
    const dok = getDocument();
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS);
    expect(getDocument()).toBe(dok);
    expect(pultStore.getState().zwischenstand?.puls).toBe(z?.puls);
    expect(pultStore.getState().ungespeichert).toBe(false);
  });

  it('fertig: die echte Fassung wird wie bisher neu geladen', async () => {
    netz({
      '/c.json': [
        [200, laeuft(ZWISCHEN_1)],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fertig', fassung_nachher: 4 })], live: null, neueste: null }],
      ],
    });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(pultStore.getState().ungespeichert).toBe(false);
  });

  it('Lauf endet ohne neue Fassung (Stopp verwerfen, Fehler): das echte Dokument kommt zurueck', async () => {
    netz({
      '/c.json': [
        [200, laeuft(ZWISCHEN_1)],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fehler', antwort: 'Gestoppt – nichts übernommen' })], live: null, neueste: null }],
      ],
    });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS);
    expect(reload).not.toHaveBeenCalled();
    expect(getDocument()).toBe(ECHT);
    expect(pultStore.getState().zwischenstand).toBeNull();
    expect(pultStore.getState().ungespeichert).toBe(false);
  });

  it('Neuladen aufgehalten (ungesicherte Aenderungen): das echte Dokument kommt zurueck, ungespeichert bleibt', async () => {
    pultStore.setState({ ungespeichert: true });
    netz({
      '/c.json': [
        [200, laeuft(ZWISCHEN_1)],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fertig', fassung_nachher: 4 })], live: null, neueste: null }],
      ],
    });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(CHAT_TAKT_MS);
    expect(reload).not.toHaveBeenCalled();
    expect(getDocument()).toBe(ECHT);
    expect(pultStore.getState().ungespeichert).toBe(true);
  });

  it('ein unbrauchbarer Zwischenstand wird nicht angezeigt (der Canvas stuerzte sonst ab)', async () => {
    const kaputt = { ...ZWISCHEN_1, root: { type: 'EmailLayout', data: { childrenIds: ['titel', 'fehlt'] } } };
    netz({ '/c.json': [[200, laeuft(kaputt)]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    expect(getDocument()).toBe(ECHT);
  });
});

describe('Stopp', () => {
  it('ruft chat_stopp_url mit art und dem laufenden Auftrag und fragt danach ab', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'a7' })], live: live(ZWISCHEN_1) as never, neueste: null } });
    const f = netz({
      '/stopp': [[200, { abgeschlossen: false }]],
      '/c.json': [[200, { laeuft: true, verlauf: [eintrag({ id: 'a7' })], live: live(ZWISCHEN_1, 1, 'behalten'), neueste: null }]],
    });
    expect(await chatStoppen('behalten', 'a7')).toBeNull();
    expect(JSON.parse(String(aufruf(f, '/stopp').body))).toEqual({ art: 'behalten', auftrag: 'a7' });
    await vi.advanceTimersByTimeAsync(0);
    expect(adressen(f)).toContain('/c.json');
    expect(pultStore.getState().chat?.live?.stopp).toBe('behalten');
  });

  it('Grund des Servers kommt zurueck', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'a7' })], live: null, neueste: null } });
    netz({ '/stopp': [[422, { grund: 'Der Assistent arbeitet gerade nicht' }]], '/c.json': [[200, { laeuft: false, verlauf: [], live: null, neueste: null }]] });
    expect(await chatStoppen('verwerfen', 'a7')).toBe('Der Assistent arbeitet gerade nicht');
  });
});
