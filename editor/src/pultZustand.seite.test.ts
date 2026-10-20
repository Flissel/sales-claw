// Assistent im Collage-Editor (Freie Fläche Stufe 3, Task 7): Speichern vor dem Senden über den
// eingesteckten Seiten-Weg, Chips gegen die Seite, Zwischenstand nur zur Anzeige.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChatEintrag } from './chat';
import { getDocument, resetDocument } from './documents/editor/EditorContext';
import type { TEditorConfiguration } from './documents/editor/core';
import type { Start } from './pult';
import { chatAbfragen, chatAbschicken, chatEntwurfWiederholen, chipsAbgleichen, editorEinstecken, pultStore } from './pultZustand';
import type { Seite } from './seite';
import { SEITE_KONFLIKT, seitenKontext, seitenSicherung, type SeitenStand } from './seiteChat';

const START = {
  format: 'seite',
  speichern_url: '/s',
  chat_url: '/c',
  chat_stand_url: '/c.json',
  chat_rueckgaengig_url: '/c/r',
  chat_stopp_url: '/stopp',
  csrf: 'm',
} as Start;

const SEITE: Seite = {
  version: 1,
  breite: 600,
  hoehe: 900,
  hintergrund: { farbe: '#ffffff', bild: null },
  schriften: { anzeige: 'playfair', text: 'dm-sans' },
  ebenen: [
    { id: 'text1', art: 'text', text: 'Hallo', rolle: 'TEXT', groesse: 17, farbe: '#333333', x: 300, y: 450, breite: 400, hoehe: 60 },
    { id: 'knopf1', art: 'knopf', text: 'Los', link: 'https://example.com', farbe: '#5b3fd6', textfarbe: '#ffffff', x: 300, y: 750, breite: 220, hoehe: 48 },
  ],
};
const ZWISCHEN: Seite = { ...SEITE, hintergrund: { farbe: '#000000', bild: null } };

const BLOCK_DOK = { root: { type: 'EmailLayout', data: { childrenIds: [] } } } as unknown as TEditorConfiguration;

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function eintrag(teil: Partial<ChatEintrag>): ChatEintrag {
  return {
    id: 'a1', art: 'chat', nachricht: 'n', antwort: '', status: 'in_arbeit', hinweise: [], ergebnis: {},
    fassung_vorher: 3, fassung_nachher: null, erstellt_am: 't', denken: '', schritte: [], schritt: '', schritt_nr: 0,
    stopp: null, bild_hinweise: [], ...teil,
  };
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
const adressen = (f: ReturnType<typeof netz>) => f.mock.calls.map((c) => c[0]);
const koerper = (f: ReturnType<typeof netz>, url: string): unknown =>
  JSON.parse(String((f.mock.calls.find((c) => c[0] === url)?.[1] as RequestInit).body));

let stand: SeitenStand;
let speicher: Map<string, string>;
let reload: ReturnType<typeof vi.fn>;
const folgen = { gespeichert: vi.fn(), konflikt: vi.fn() };
let ausstecken: () => void;

beforeEach(() => {
  vi.useFakeTimers();
  speicher = new Map<string, string>();
  reload = vi.fn();
  vi.stubGlobal('window', { location: { reload } });
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => speicher.get(k) ?? null,
    setItem: (k: string, v: string) => void speicher.set(k, v),
    removeItem: (k: string) => void speicher.delete(k),
  });
  pultStore.setState({
    start: START, basis: 3, ungespeichert: true, hinweisOffen: false, chat: null, zwischenstand: null,
    seitenZwischenstand: null, fassungWartet: null, chatAuswahl: [], chatAnhaenge: [], chatHinweis: null, nurLesen: false,
    gesendeteAuswahl: null, chatText: '', geladenUm: Date.now(), gestaltungOffen: null, gestaltungGeaendert: false,
  });
  resetDocument(BLOCK_DOK);
  stand = { seite: SEITE, betreff: 'B', vorschautext: 'V', basis: 3, ungespeichert: true };
  folgen.gespeichert.mockReset();
  folgen.konflikt.mockReset();
  ausstecken = editorEinstecken({ sichern: seitenSicherung(START, () => stand, folgen), dokument: () => ({ ...stand.seite }) });
});

afterEach(() => {
  ausstecken();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('vor dem Senden (Collage)', () => {
  it('speichert Ungespeichertes mit seiteSpeichern, danach geht die Nachricht mit fenster seite', async () => {
    const f = netz({
      '/s': [[200, { fassung: 4 }]],
      '/c': [[200, { auftrag: 'a1', status: 'offen' }]],
      '/c.json': [[200, { laeuft: true, verlauf: [eintrag({ status: 'offen' })], live: null, neueste: null }]],
    });
    const grund = await chatAbschicken('Mach es ruhiger', { fenster: 'seite', auswahl: null });
    expect(grund).toBeNull();
    expect(adressen(f).slice(0, 2)).toEqual(['/s', '/c']);
    expect(koerper(f, '/s')).toMatchObject({ basis_fassung: 3, seite: SEITE, betreff: 'B', vorschautext: 'V', als_kopie: false });
    expect(koerper(f, '/c')).toMatchObject({ nachricht: 'Mach es ruhiger', kontext: { fenster: 'seite' } });
    expect(folgen.gespeichert).toHaveBeenCalledWith(4);
    expect(pultStore.getState().basis).toBe(4);
  });

  it('bei Konflikt: Konfliktdialog, nichts wird gesendet', async () => {
    const f = netz({ '/s': [[409, { grund: 'veraltet' }]], '/c': [[200, { auftrag: 'a1', status: 'offen' }]] });
    const grund = await chatAbschicken('Mach es ruhiger', { fenster: 'seite', auswahl: null });
    expect(grund).toBe(SEITE_KONFLIKT);
    expect(folgen.konflikt).toHaveBeenCalledTimes(1);
    expect(adressen(f)).toEqual(['/s']);
    expect(pultStore.getState().basis).toBe(3);
  });

  it('ungültige Seite: Grund, weder speichern noch senden', async () => {
    stand = { ...stand, seite: { ...SEITE, ebenen: [{ ...SEITE.ebenen[0], text: '' } as Seite['ebenen'][number]] } };
    const f = netz({ '/s': [[200, { fassung: 4 }]], '/c': [[200, { auftrag: 'a1', status: 'offen' }]] });
    const grund = await chatAbschicken('x', { fenster: 'seite', auswahl: null });
    expect(grund).not.toBeNull();
    expect(adressen(f)).toEqual([]);
  });

  it('nichts geändert: sendet ohne zu speichern', async () => {
    stand = { ...stand, ungespeichert: false };
    pultStore.setState({ ungespeichert: false });
    const f = netz({
      '/c': [[200, { auftrag: 'a1', status: 'offen' }]],
      '/c.json': [[200, { laeuft: true, verlauf: [eintrag({ status: 'offen' })], live: null, neueste: null }]],
    });
    expect(await chatAbschicken('x', { fenster: 'seite', auswahl: null })).toBeNull();
    expect(adressen(f)[0]).toBe('/c');
  });

  it('Chips einer Seiten-Ebene gehen als art ebene ohne flaeche mit; verschwundene fallen weg', async () => {
    stand = { ...stand, ungespeichert: false };
    pultStore.setState({
      ungespeichert: false,
      chatAuswahl: [{ art: 'ebene', id: 'text1', kurz: 'Text-Ebene · Hallo' }, { art: 'ebene', id: 'weg', kurz: 'Text-Ebene · alt' }],
    });
    const f = netz({
      '/c': [[200, { auftrag: 'a1', status: 'offen' }]],
      '/c.json': [[200, { laeuft: true, verlauf: [eintrag({ status: 'offen' })], live: null, neueste: null }]],
    });
    expect(await chatAbschicken('größer', { fenster: 'seite', auswahl: null })).toBeNull();
    expect(koerper(f, '/c')).toEqual({
      nachricht: 'größer',
      kontext: { fenster: 'seite', auswahl: [{ art: 'ebene', id: 'text1', kurz: 'Text-Ebene · Hallo' }] },
    });
  });
});

describe('Zwischenstand (Collage)', () => {
  it('wird nur angezeigt: kein Block-Dokument, nicht ungespeichert, endet ohne Spuren', async () => {
    pultStore.setState({ ungespeichert: false });
    const lauf = { laeuft: true, verlauf: [eintrag({})], live: { schritt: 'Ebenen setzen', schritt_nr: 1, zwischenstand: { seite: ZWISCHEN }, stopp: null }, neueste: null };
    const antworten = netz({
      '/c.json': [
        [200, lauf],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fehler' })], live: null, neueste: null }],
      ],
    });
    const netzVon = () => antworten;
    const vorher = getDocument();
    const f = netzVon();
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    expect(pultStore.getState().seitenZwischenstand).toEqual(ZWISCHEN);
    expect(pultStore.getState().zwischenstand).toBeNull();
    expect(pultStore.getState().ungespeichert).toBe(false);
    expect(getDocument()).toBe(vorher);
    // Nichts wurde gespeichert: nur der Chat-Stand wurde abgefragt.
    expect(adressen(f)).toEqual(['/c.json']);
    await vi.advanceTimersByTimeAsync(1000);
    expect(pultStore.getState().seitenZwischenstand).toBeNull();
    expect(getDocument()).toBe(vorher);
  });

  it('kaputter Zwischenstand wird nicht gezeigt', async () => {
    const lauf = { laeuft: true, verlauf: [eintrag({})], live: { schritt: '', schritt_nr: 1, zwischenstand: { seite: { ebenen: 'x' } }, stopp: null }, neueste: null };
    netz({ '/c.json': [[200, lauf]] });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    expect(pultStore.getState().seitenZwischenstand).toBeNull();
  });
});

describe('gewählte Ebene geht von selbst mit (Collage)', () => {
  const lauf = { laeuft: true, verlauf: [eintrag({ status: 'offen' })], live: null, neueste: null };

  it('ohne Chips: die gewählte Ebene als Listeneintrag {art: ebene, id, kurz}, nie als Einzelform', async () => {
    stand = { ...stand, ungespeichert: false };
    const f = netz({ '/c': [[200, { auftrag: 'a1', status: 'offen' }]], '/c.json': [[200, lauf]] });
    expect(await chatAbschicken('größer', seitenKontext(SEITE.ebenen[0]))).toBeNull();
    expect(koerper(f, '/c')).toEqual({
      nachricht: 'größer',
      kontext: { fenster: 'seite', auswahl: [{ art: 'ebene', id: 'text1', kurz: 'Text-Ebene · Hallo' }] },
    });
  });

  it('angehängte Chips ersetzen die Auswahl; ohne Auswahl geht auswahl null', async () => {
    stand = { ...stand, ungespeichert: false };
    pultStore.setState({ chatAuswahl: [{ art: 'ebene', id: 'knopf1', kurz: 'Knopf-Ebene · Los' }] });
    const f = netz({ '/c': [[200, { auftrag: 'a1', status: 'offen' }]], '/c.json': [[200, lauf]] });
    expect(await chatAbschicken('x', seitenKontext(SEITE.ebenen[0]))).toBeNull();
    expect(koerper(f, '/c')).toMatchObject({ kontext: { auswahl: [{ art: 'ebene', id: 'knopf1', kurz: 'Knopf-Ebene · Los' }] } });
    expect(seitenKontext(null)).toEqual({ fenster: 'seite', auswahl: null });
  });
});

describe('wiederhergestellte Chips (Collage, nach dem Neuladen)', () => {
  it('überleben den ersten Abgleich, auch wenn der Editor noch nicht eingesteckt ist', () => {
    ausstecken();
    speicher.set('vibemind-chat-chips', JSON.stringify({
      auswahl: [{ art: 'ebene', id: 'text1', kurz: 'Text-Ebene · Hallo' }, { art: 'ebene', id: 'weg', kurz: 'Text-Ebene · alt' }],
      anhaenge: [],
    }));
    chatEntwurfWiederholen();
    // Erster Abgleich vor dem Einstecken (Block-Dokument ist leer): nichts fällt weg, kein Hinweis.
    chipsAbgleichen();
    expect(pultStore.getState().chatAuswahl.map((c) => c.id)).toEqual(['text1', 'weg']);
    expect(pultStore.getState().chatHinweis).toBeNull();
    // Beim Einstecken gleicht der Editor gegen die Seite ab: nur die verschwundene Ebene fällt weg.
    ausstecken = editorEinstecken({ sichern: seitenSicherung(START, () => stand, folgen), dokument: () => ({ ...stand.seite }) });
    expect(pultStore.getState().chatAuswahl.map((c) => c.id)).toEqual(['text1']);
    expect(pultStore.getState().chatHinweis).toBe('1 markiertes Element gibt es nicht mehr – entfernt');
  });
});

describe('Neuladen nach der Runde wartet (Collage)', () => {
  it('abgewiesen wegen Ungespeichertem: lädt nach, sobald nichts mehr ungespeichert ist', async () => {
    netz({
      '/c.json': [
        [200, { laeuft: true, verlauf: [eintrag({})], live: null, neueste: null }],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fertig', fassung_nachher: 5 })], live: null, neueste: 5 }],
      ],
    });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(reload).not.toHaveBeenCalled();
    expect(pultStore.getState().fassungWartet).toBe(5);
    pultStore.setState({ ungespeichert: false });
    expect(reload).toHaveBeenCalledTimes(1);
    expect(pultStore.getState().fassungWartet).toBeNull();
  });

  it('abgewiesen wegen laufendem Upload: lädt nach, wenn der Upload fertig ist', async () => {
    pultStore.setState({ ungespeichert: false, chatAnhaenge: [{ id: 'x', name: 'a.png', art: 'bild', status: 'laedt', fortschritt: 0.5 }] });
    netz({
      '/c.json': [
        [200, { laeuft: true, verlauf: [eintrag({})], live: null, neueste: null }],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fertig', fassung_nachher: 5 })], live: null, neueste: 5 }],
      ],
    });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(reload).not.toHaveBeenCalled();
    pultStore.setState({ chatAnhaenge: [{ id: 'x', name: 'a.png', art: 'bild', status: 'fertig', fortschritt: 1 }] });
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('inzwischen eigene neuere Fassung gespeichert (Kopie): kein Nachladen, Hinweis weg', async () => {
    netz({
      '/c.json': [
        [200, { laeuft: true, verlauf: [eintrag({})], live: null, neueste: null }],
        [200, { laeuft: false, verlauf: [eintrag({ status: 'fertig', fassung_nachher: 5 })], live: null, neueste: 5 }],
      ],
    });
    chatAbfragen();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000);
    pultStore.setState({ basis: 6 });
    expect(pultStore.getState().fassungWartet).toBeNull();
    pultStore.setState({ ungespeichert: false });
    expect(reload).not.toHaveBeenCalled();
  });
});
