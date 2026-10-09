import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChatEintrag } from './chat';
import { resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import { chatAbfragen, chatAbschicken, chatEntwurfWiederholen, chatTextSetzen, pultStore } from './pultZustand';

const START = { speichern_url: '/s', chat_url: '/c', chat_stand_url: '/c.json', chat_rueckgaengig_url: '/c/r', csrf: 'm' } as Start;

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function eintrag(teil: Partial<ChatEintrag>): ChatEintrag {
  return { id: 'a1', art: 'chat', nachricht: 'n', antwort: '', status: 'in_arbeit', hinweise: [], ergebnis: {},
    fassung_vorher: 3, fassung_nachher: null, erstellt_am: 't', denken: '', schritte: [], schritt: '', schritt_nr: 0,
    stopp: null, bild_hinweise: [], ...teil };
}

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
  pultStore.setState({ start: START, basis: 3, ungespeichert: false, hinweisOffen: false, gestaltungOffen: null,
    gestaltungGeaendert: false, chat: null, chatText: '', chatAuswahl: [], chatAnhaenge: [] });
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('Mehrere Runden', () => {
  it('Senden während laufender Runden: POST an chat_url, Eintrag mit dem Status des Servers', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'r1' }), eintrag({ id: 'r2' })], live: null, neueste: 3 } });
    const stand = { laeuft: true, verlauf: [eintrag({ id: 'r1' }), eintrag({ id: 'r2' }), eintrag({ id: 'r3', status: 'wartet' })], neueste_fassung: 3 };
    const f = netz({ '/c': [[200, { auftrag: 'r3', status: 'wartet' }]], '/c.json': [[200, stand]] });
    expect(await chatAbschicken('Noch was', { fenster: 'newsletter', auswahl: null })).toBeNull();
    expect(f.mock.calls[0][0]).toBe('/c');
    const letzter = pultStore.getState().chat?.verlauf.find((e) => e.id === 'r3');
    expect(letzter?.status).toBe('wartet');
  });

  it('ein laufender Newsletter-Export sperrt weiter', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'x', art: 'export' })], live: null, neueste: 3 } });
    const f = netz({});
    expect(await chatAbschicken('Hallo', { fenster: 'newsletter', auswahl: null })).toBe('Der Assistent arbeitet gerade');
    expect(f).not.toHaveBeenCalled();
  });

  it('Entwurf im Eingabefeld überlebt das Neuladen nach einer fertigen Runde', async () => {
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'r1' })], live: null, neueste: 3 } });
    chatTextSetzen('Und dann den Fuß kürzer');
    netz({ '/c.json': [[200, { laeuft: false, verlauf: [eintrag({ id: 'r1', status: 'fertig', fassung_nachher: 4 })], neueste_fassung: 4 }]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(10);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(speicher.get('vibemind-chat-entwurf')).toBe('Und dann den Fuß kürzer');
    pultStore.setState({ chatText: '' });          // neu geladen
    chatEntwurfWiederholen();
    expect(pultStore.getState().chatText).toBe('Und dann den Fuß kürzer');
    expect(speicher.has('vibemind-chat-entwurf')).toBe(false);
  });
});
