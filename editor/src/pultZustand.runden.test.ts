import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChatEintrag } from './chat';
import { resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import { chatAbfragen, chatAbschicken, chatEingabeSenden, chatEntwurfWiederholen, chatTextSetzen, pultStore, standAbfragen } from './pultZustand';
import type { AnhangChip, AuswahlChip } from './chatKontext';

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

  it('Chips und fertige Anhänge überleben das Neuladen nach einer fertigen Runde', async () => {
    const auswahl: AuswahlChip[] = [{ art: 'block', id: 't', kurz: 'Titel' }, { art: 'ebene', id: 'e-1', flaeche: 'f', kurz: 'Logo', alt: true }];
    const anhaenge: AnhangChip[] = [
      { id: 'anhang-7', name: 'foto.jpg', art: 'bild', status: 'fertig', fortschritt: 1, vorschau: 'blob:weg' },
      { id: 'anhang-8', name: 'x.exe', art: 'dokument', status: 'fehler', grund: 'Typ', fortschritt: 0 },
    ];
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'r1' })], live: null, neueste: 3 }, chatAuswahl: auswahl, chatAnhaenge: anhaenge });
    netz({ '/c.json': [[200, { laeuft: false, verlauf: [eintrag({ id: 'r1', status: 'fertig', fassung_nachher: 4 })], neueste_fassung: 4 }]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(10);
    expect(reload).toHaveBeenCalledTimes(1);
    pultStore.setState({ chatAuswahl: [], chatAnhaenge: [] });          // neu geladen
    chatEntwurfWiederholen();
    expect(pultStore.getState().chatAuswahl).toEqual(auswahl);
    const da = pultStore.getState().chatAnhaenge;
    expect(da.map(({ name, art, status }) => ({ name, art, status }))).toEqual([{ name: 'foto.jpg', art: 'bild', status: 'fertig' }]);
    expect(da[0].vorschau).toBeUndefined();
    expect([...speicher.keys()].filter((k) => k.startsWith('vibemind-chat'))).toEqual([]);
  });

  it('wiederhergestellte Anhänge bekommen neue ids, kaputter Speicher wird ignoriert', () => {
    speicher.set('vibemind-chat-chips', JSON.stringify({ auswahl: [{ art: 'block', id: 't', kurz: 'T' }, { art: 'x', id: 1 }],
      anhaenge: [{ id: 'anhang-1', name: 'a.png', art: 'bild', status: 'fertig', fortschritt: 1 }, { name: 'b.png', art: 'bild', status: 'laedt' }] }));
    chatEntwurfWiederholen();
    expect(pultStore.getState().chatAuswahl).toEqual([{ art: 'block', id: 't', kurz: 'T' }]);
    expect(pultStore.getState().chatAnhaenge.map((a) => a.name)).toEqual(['a.png']);
    pultStore.setState({ chatAuswahl: [], chatAnhaenge: [] });
    speicher.set('vibemind-chat-chips', '{kaputt');
    expect(() => chatEntwurfWiederholen()).not.toThrow();
    expect(pultStore.getState().chatAuswahl).toEqual([]);
    vi.stubGlobal('sessionStorage', { getItem: () => { throw new Error('gesperrt'); }, setItem: () => { throw new Error('gesperrt'); }, removeItem: () => undefined });
    expect(() => chatEntwurfWiederholen()).not.toThrow();
  });

  it('ohne Speicher lädt die Seite trotzdem neu', async () => {
    vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => { throw new Error('voll'); }, removeItem: () => undefined });
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'r1' })], live: null, neueste: 3 },
      chatAuswahl: [{ art: 'block', id: 't', kurz: 'T' }], chatText: 'x' });
    netz({ '/c.json': [[200, { laeuft: false, verlauf: [eintrag({ id: 'r1', status: 'fertig', fassung_nachher: 4 })], neueste_fassung: 4 }]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(10);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('Neuladen wartet, solange ein Anhang hochlädt; der Stand-Abruf holt die Fassung danach', async () => {
    pultStore.setState({ start: { ...START, stand_url: '/st' } as Start,
      chat: { laeuft: true, verlauf: [eintrag({ id: 'r1' })], live: null, neueste: 3 },
      chatAnhaenge: [{ id: 'anhang-9', name: 'foto.jpg', art: 'bild', status: 'laedt', fortschritt: 0.5 }] });
    netz({ '/c.json': [[200, { laeuft: false, verlauf: [eintrag({ id: 'r1', status: 'fertig', fassung_nachher: 4 })], neueste_fassung: 4 }]],
      '/st': [[200, { fassung: 4, auftraege: [] }]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(10);
    expect(reload).not.toHaveBeenCalled();
    standAbfragen();
    await vi.advanceTimersByTimeAsync(10);
    expect(reload).not.toHaveBeenCalled();                 // laedt noch
    pultStore.setState({ chatAnhaenge: [{ id: 'anhang-9', name: 'foto-2.jpg', art: 'bild', status: 'fertig', fortschritt: 1 }] });
    await vi.advanceTimersByTimeAsync(15000);
    expect(reload).toHaveBeenCalledTimes(1);
    pultStore.setState({ chatAnhaenge: [] });
    chatEntwurfWiederholen();
    expect(pultStore.getState().chatAnhaenge.map((a) => a.name)).toEqual(['foto-2.jpg']);
  });
});

describe('Senden aus dem Eingabefeld', () => {
  const DOK = { root: { type: 'EmailLayout', data: { childrenIds: ['t'] } }, t: { type: 'Text', data: { props: { text: 'Titel' } } } };
  const K = { fenster: 'newsletter', auswahl: null } as const;

  // POST /c haengt, bis loslassen() ihn beantwortet; /c.json meldet die fertige Runde r1 mit Fassung 4.
  function haengendesSenden(status = 200, body: unknown = { auftrag: 'r2', status: 'offen' }) {
    let loslassen: () => void = () => undefined;
    const fertig = new Promise<void>((r) => { loslassen = r; });
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/c') { await fertig; return antwort(status, body); }
      return antwort(200, { laeuft: true, verlauf: [eintrag({ id: 'r1', status: 'fertig', fassung_nachher: 4 }), eintrag({ id: 'r2', status: 'offen' })], neueste_fassung: 4 });
    }));
    return () => loslassen();
  }

  beforeEach(() => {
    resetDocument(DOK as unknown as TEditorConfiguration);
    pultStore.setState({ chat: { laeuft: true, verlauf: [eintrag({ id: 'r1' })], live: null, neueste: 3 } });
  });

  it('Neuladen während des Sendens bringt die gesendete Bitte und ihre Chips nicht frisch zurück', async () => {
    pultStore.setState({ chatAuswahl: [{ art: 'block', id: 't', kurz: 'Titel' }] });
    chatTextSetzen('Titel kürzer');
    const loslassen = haengendesSenden();
    const p = chatEingabeSenden(K);
    expect(pultStore.getState().chatText).toBe('');
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(10);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(speicher.has('vibemind-chat-entwurf')).toBe(false);
    loslassen();
    expect(await p).toBeNull();
    pultStore.setState({ chatText: '', chatAuswahl: [] });          // neu geladen
    chatEntwurfWiederholen();
    expect(pultStore.getState().chatText).toBe('');
    expect(pultStore.getState().chatAuswahl).toEqual([{ art: 'block', id: 't', kurz: 'Titel', alt: true }]);
  });

  it('was während des Sendens getippt wird, bleibt stehen', async () => {
    chatTextSetzen('Erste Bitte');
    const loslassen = haengendesSenden();
    const p = chatEingabeSenden(K);
    chatTextSetzen('Zweite Bitte');
    loslassen();
    expect(await p).toBeNull();
    expect(pultStore.getState().chatText).toBe('Zweite Bitte');
  });

  it('scheitert das Senden, kommt der Text zurück – nur in ein leeres Feld', async () => {
    chatTextSetzen('Erste Bitte');
    let loslassen = haengendesSenden(409, { grund: 'Bitte warten, bis eine Runde fertig ist' });
    let p = chatEingabeSenden(K);
    loslassen();
    expect(await p).toBe('Bitte warten, bis eine Runde fertig ist');
    expect(pultStore.getState().chatText).toBe('Erste Bitte');
    loslassen = haengendesSenden(409, { grund: 'Bitte warten, bis eine Runde fertig ist' });
    p = chatEingabeSenden(K);
    chatTextSetzen('Schon was Neues');
    loslassen();
    expect(await p).toBe('Bitte warten, bis eine Runde fertig ist');
    expect(pultStore.getState().chatText).toBe('Schon was Neues');
  });
});
