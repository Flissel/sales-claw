import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Start } from '../../pult';
import { LIEGT_ZUR_FREIGABE, pultStarten, pultStore } from '../../pultZustand';
import type { Seite } from '../../seite';

import SeiteApp, { ARBEITET_HINWEIS, NEUE_FASSUNG_HINWEIS, nurEinmal, seiteEinreichen } from './SeiteApp';
import SeitenChat from './SeitenChat';

const IID = 'b12c46b9-8f87-412b-b2e7-7215b354a75b';

export const SEITE: Seite = {
  version: 1,
  breite: 600,
  hoehe: 900,
  hintergrund: { farbe: '#fdf8f0', bild: null },
  schriften: { anzeige: 'playfair', text: 'dm-sans' },
  ebenen: [
    { id: 'bild1', art: 'bild', quelle: 'medien:foto-1.png', x: 300, y: 200, breite: 400, hoehe: 300, rahmen_breite: 6, rahmen_farbe: '#ffffff', kreis: false, schatten: true, passung: 'einpassen' },
    { id: 'text1', art: 'text', text: 'Hallo **Welt**', rolle: 'TEXT', groesse: 17, farbe: '#333333', x: 300, y: 450, breite: 400, hoehe: 60, buchstabenabstand: 0.05 },
    { id: 'form1', art: 'form', form: 'kreis', farbe: '#5b3fd6', x: 100, y: 600, breite: 120, hoehe: 120, drehung: 15, deckkraft: 0.5 },
    { id: 'knopf1', art: 'knopf', text: 'Mehr erfahren', link: 'https://example.com', farbe: '#5b3fd6', textfarbe: '#ffffff', x: 300, y: 750, breite: 220, hoehe: 48 },
  ],
};

export function seitenStart(seite: Seite = SEITE): Start {
  return {
    format: 'seite',
    seite,
    dokument: null,
    betreff: 'Oktober-Collage',
    vorschautext: 'Kurz',
    basis_fassung: 3,
    speichern_url: `/marketing/editor/${IID}/seite`,
    vorschau_url: `/marketing/entwurf/${IID}/vorschau`,
    medien_url: `/marketing/editor/medien.json?iid=${IID}`,
    gestaltung_url: '',
    stand_url: '',
    chat_url: '',
    chat_stand_url: '',
    chat_rueckgaengig_url: '',
    chat_stopp_url: '',
    export_vorschau_url: '',
    export_url: '',
    zurueck_url: `/marketing/entwurf/${IID}`,
    csrf: 'marke-1',
  };
}

describe('SeiteApp', () => {
  const html = renderToStaticMarkup(<SeiteApp start={seitenStart()} />);

  it('zeigt die Ebenen in Array-Reihenfolge (erste unten)', () => {
    const lagen = ['bild1', 'text1', 'form1', 'knopf1'].map((id) => html.indexOf(`data-ebene="${id}"`));
    expect(lagen.every((i) => i >= 0)).toBe(true);
    expect([...lagen].sort((a, b) => a - b)).toEqual(lagen);
  });

  it('Knopf erbt keine MUI-Zeilenhöhe/-Laufweite (PDF: normal)', () => {
    expect(html).toMatch(/data-ebene="knopf1"[^>]*line-height:normal/);
    expect(html).toMatch(/data-ebene="knopf1"[^>]*letter-spacing:normal/);
  });

  it('zeigt Bilder über die Medien-Adresse, nie als medien:', () => {
    expect(html).toContain('src="/medien/datei/foto-1.png"');
    expect(html).not.toContain('src="medien:');
  });

  it('Fließtext nur im mail-sicheren Stapel', () => {
    expect(html).toContain('font-family:Arial, Helvetica, sans-serif');
    expect(html).toContain('<strong>Welt</strong>');
  });

  it('Ebenen wie seite_html: border-box, Rahmen, Schatten, Passung, Drehung, Deckkraft', () => {
    expect(html).toContain('box-sizing:border-box');
    expect(html).toContain('border:6px solid #ffffff');
    expect(html).toContain('box-shadow:0 4px 14px rgba(0,0,0,0.3)');
    expect(html).toContain('object-fit:contain');
    expect(html).toContain('transform:rotate(15deg)');
    expect(html).toContain('opacity:0.5');
    expect(html).toContain('letter-spacing:0.05em');
    expect(html).toContain('min-height:60px');
  });

  it('Seite wie seite_html: 600 breit, Anschnitt, Hintergrund; Ebenen mit z-index; Knopf ohne Link', () => {
    expect(html).toContain('position:relative;width:600px;height:900px;overflow:hidden;background-color:#fdf8f0');
    expect(html).toMatch(/data-ebene="knopf1"[^>]*z-index:3/);
    expect(html).toContain('justify-content:center');
    expect(html).toContain('>Mehr erfahren</div>');
    expect(html).not.toContain('href="https://example.com"');
  });

  it('zeigt den Assistenten (Chat); ohne einreichen_url kein Einreichen', () => {
    expect(html).toContain('Nachricht an den Assistenten');
    expect(html).not.toContain('Der Assistent kommt');
    expect(html).not.toContain(ARBEITET_HINWEIS);
    expect(html).not.toContain('Einreichen');
  });

  it('hat Leiste mit Betreff, Speichern, Als PDF, Rückgängig und die Ebenen-Knöpfe', () => {
    expect(html).toContain('value="Oktober-Collage"');
    expect(html).toContain('Speichern');
    expect(html).toContain('Als PDF');
    expect(html).toContain('aria-label="Rückgängig"');
    for (const k of ['Text', 'Bild', 'Form', 'Knopf']) expect(html).toContain(`>${k}</button>`);
    expect(html).toContain(`href="/marketing/entwurf/${IID}"`);
  });

  it('rendert keinen Block-Editor', () => {
    expect(html).not.toContain('data-block');
    expect(html).not.toContain('Abschnitte');
    expect(html).not.toContain('Inhalt einfügen');
  });

  it('sperrt das Hinzufügen bei 80 Ebenen mit Hinweis', () => {
    const voll: Seite = {
      ...SEITE,
      ebenen: Array.from({ length: 80 }, (_, i) => ({ id: `f${i}`, art: 'form' as const, form: 'rechteck' as const, farbe: '#000000', x: 300, y: 300, breite: 10, hoehe: 10 })),
    };
    const h = renderToStaticMarkup(<SeiteApp start={seitenStart(voll)} />);
    expect(h).toContain('Höchstens 80 Ebenen');
  });

  it('ohne Seite: verständlicher Fehler statt Absturz', () => {
    const s = { ...seitenStart(), seite: undefined };
    expect(renderToStaticMarkup(<SeiteApp start={s} />)).toContain('Die Collage konnte nicht geladen werden');
  });
});

// zustand rendert auf dem Server den INITIAL-Zustand; fuer den Aufruf auf den aktuellen Stand setzen.
const INITIAL = { ...pultStore.getInitialState() };
function rendern(el: React.ReactElement): string {
  Object.assign(pultStore.getInitialState(), pultStore.getState());
  try {
    return renderToStaticMarkup(el);
  } finally {
    Object.assign(pultStore.getInitialState(), INITIAL);
  }
}

describe('SeiteApp mit Assistent', () => {
  afterEach(() => pultStore.setState({ chat: null, seitenZwischenstand: null, chatAuswahl: [], fassungWartet: null }));

  it('bietet die gewählte Ebene als Chip an (Kurzname aus Art und Textanfang)', () => {
    const h = rendern(<SeitenChat ebene={SEITE.ebenen[1]} />);
    expect(h).toContain('Text-Ebene · Hallo Welt');
    expect(h).toContain('Als Kontext anhängen: Text-Ebene · Hallo Welt');
    // Schon als Chip dran: kein zweites Angebot.
    pultStore.setState({ chatAuswahl: [{ art: 'ebene', id: 'text1', kurz: 'Text-Ebene · Hallo Welt' }] });
    expect(rendern(<SeitenChat ebene={SEITE.ebenen[1]} />)).not.toContain('Als Kontext anhängen');
    // Ohne Auswahl kein Angebot.
    pultStore.setState({ chatAuswahl: [] });
    expect(rendern(<SeitenChat ebene={null} />)).not.toContain('Als Kontext anhängen');
  });

  it('während einer Runde: Zwischenstand nur zur Anzeige, Hinweis „Der Assistent arbeitet“', () => {
    expect(ARBEITET_HINWEIS).toBe('Der Assistent arbeitet');
    pultStore.setState({
      chat: { laeuft: true, verlauf: [], live: null, neueste: null },
      seitenZwischenstand: { ...SEITE, hintergrund: { farbe: '#123456', bild: null }, ebenen: [SEITE.ebenen[1]] },
    });
    const h = rendern(<SeiteApp start={seitenStart()} />);
    expect(h).toContain(ARBEITET_HINWEIS);
    expect(h).toContain('background-color:#123456');
    // Die Fläche zeigt den Zwischenstand, nicht die eigene Seite ...
    expect(h).not.toContain('data-ebene="bild1"');
    expect(h).toContain('data-ebene="text1"');
    // ... die Ebenenliste bleibt beim echten Stand (vier Ebenen, je ein Löschen-Knopf).
    expect(h.split('aria-label="Löschen"').length - 1).toBe(4);
  });

  it('gesperrt: Speichern, Rückgängig, Wiederholen und Betreff sind deaktiviert (frei: Speichern und Betreff nicht)', () => {
    const knopf = (h: string, text: string) => {
      const i = h.indexOf(text);
      const start = h.lastIndexOf('<button', i);
      return h.slice(start, h.indexOf('>', start) + 1);
    };
    const eingabe = (h: string) => {
      const i = h.indexOf('aria-label="Betreff"');
      const start = h.lastIndexOf('<input', i);
      return h.slice(start, h.indexOf('>', i) + 1);
    };
    const frei = rendern(<SeiteApp start={seitenStart()} />);
    expect(knopf(frei, 'Speichern</button>')).not.toContain('disabled');
    expect(eingabe(frei)).not.toContain('disabled');

    pultStore.setState({ chat: { laeuft: true, verlauf: [], live: null, neueste: null } });
    const h = rendern(<SeiteApp start={seitenStart()} />);
    expect(knopf(h, 'Speichern</button>')).toContain('disabled');
    expect(knopf(h, 'aria-label="Rückgängig"')).toContain('disabled');
    expect(knopf(h, 'aria-label="Wiederholen"')).toContain('disabled');
    expect(eingabe(h)).toContain('disabled');
  });

  it('wartende neue Fassung des Assistenten: Hinweis zum Speichern und Neuladen', () => {
    expect(NEUE_FASSUNG_HINWEIS).toBe('Neue Fassung vom Assistenten – bitte speichern und neu laden');
    pultStore.setState({ fassungWartet: 5 });
    expect(rendern(<SeiteApp start={seitenStart()} />)).toContain(NEUE_FASSUNG_HINWEIS);
  });
});

// Freie Fläche Stufe 4: Einreichen aus dem Collage-Editor; eingereicht = nur lesend.
describe('SeiteApp einreichen und nur lesend', () => {
  const mitUrls = (teil: Partial<Start> = {}): Start => ({
    ...seitenStart(),
    einreichen_url: `/marketing/editor/${IID}/einreichen`,
    zurueckziehen_url: `/marketing/editor/${IID}/zurueckziehen`,
    ...teil,
  });
  const knopf = (h: string, text: string) => {
    const i = h.indexOf(text);
    const start = h.lastIndexOf('<button', i);
    return h.slice(start, h.indexOf('>', start) + 1);
  };
  afterEach(() => {
    vi.unstubAllGlobals();
    pultStore.setState({ start: null, nurLesen: false, chat: null, ungespeichert: false });
  });

  it('Entwurf mit einreichen_url: Einreichen-Knopf in der Leiste, kein Hinweis', () => {
    pultStarten(mitUrls({ status: 'entwurf' }));
    const h = rendern(<SeiteApp start={mitUrls({ status: 'entwurf' })} />);
    expect(h).toContain('>Einreichen</button>');
    expect(knopf(h, '>Einreichen</button>')).not.toContain('disabled');
    expect(h).not.toContain(LIEGT_ZUR_FREIGABE);
    expect(h).toContain('aria-label="Seitenhöhe"');
  });

  it('eingereicht: Speichern und Rückgängig gesperrt, keine Griffe, Hinweis und Zurückziehen, kein Einreichen', () => {
    expect(LIEGT_ZUR_FREIGABE).toBe('Liegt zur Freigabe – erst zurückziehen');
    const s = mitUrls({ status: 'eingereicht', eingereicht_am: '2026-10-20T08:00:00+00:00' });
    pultStarten(s);
    const h = rendern(<SeiteApp start={s} />);
    expect(knopf(h, 'Speichern</button>')).toContain('disabled');
    expect(knopf(h, 'aria-label="Rückgängig"')).toContain('disabled');
    expect(h).not.toContain('aria-label="Seitenhöhe"');
    expect(h).not.toContain('aria-label="Größe');
    expect(h).not.toContain('aria-label="Drehen"');
    expect(h).toContain(LIEGT_ZUR_FREIGABE);
    expect(h).toContain('>Zurückziehen</button>');
    expect(h).not.toContain('>Einreichen</button>');
    // Betreff gesperrt, die Seite bleibt sichtbar
    const i = h.indexOf('aria-label="Betreff"');
    expect(h.slice(h.lastIndexOf('<input', i), h.indexOf('>', i) + 1)).toContain('disabled');
    expect(h).toContain('data-ebene="bild1"');
  });

  it('Einreichen ruft einreichenAuftrag: der 422-Grund wird zur Fehlermeldung', async () => {
    pultStarten(mitUrls({ status: 'entwurf' }));
    pultStore.setState({ chat: null });
    const grund = 'Die Anrede steht in einem Bildbereich – sie muss in frei stehendem Fließtext stehen';
    const f = vi.fn(async () => new Response(JSON.stringify({ grund }), { status: 422, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', f);
    expect(await seiteEinreichen()).toEqual({ art: 'error', text: grund });
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe(`/marketing/editor/${IID}/einreichen`);
    expect(pultStore.getState().nurLesen).toBe(false);
  });

  it('Einreichen erfolgreich: Meldung und nur lesend', async () => {
    pultStarten(mitUrls({ status: 'entwurf' }));
    pultStore.setState({ chat: null });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ status: 'eingereicht', fassung: 3 }), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    expect(await seiteEinreichen()).toEqual({ art: 'success', text: 'Zur Freigabe eingereicht' });
    expect(pultStore.getState().nurLesen).toBe(true);
  });
});

describe('Einreichen: Doppelklick-Schutz', () => {
  it('ein zweiter Klick, solange das erste Einreichen läuft, löst nichts aus; danach wieder', async () => {
    const sperre = { current: false };
    let fertig: (wert: string) => void = () => undefined;
    const lauf = vi.fn(() => new Promise<string>((r) => { fertig = r; }));
    const erster = nurEinmal(sperre, lauf);
    // zweiter Klick im selben Takt (React hat noch nicht neu gerendert)
    expect(await nurEinmal(sperre, lauf)).toBeUndefined();
    expect(lauf).toHaveBeenCalledTimes(1);
    fertig('ok');
    expect(await erster).toBe('ok');
    expect(sperre.current).toBe(false);
    const dritter = nurEinmal(sperre, lauf);
    fertig('wieder');
    expect(await dritter).toBe('wieder');
    expect(lauf).toHaveBeenCalledTimes(2);
  });

  it('gibt die Sperre auch nach einem Fehler frei', async () => {
    const sperre = { current: false };
    await expect(nurEinmal(sperre, () => Promise.reject(new Error('weg')))).rejects.toThrow('weg');
    expect(sperre.current).toBe(false);
  });
});

describe('Knopf „Prüfen“ in der Leiste', () => {
  it('mit pruefung_url: Knopf da, Liste erst nach dem Klick', () => {
    const html = renderToStaticMarkup(<SeiteApp start={{ ...seitenStart(), pruefung_url: '/marketing/editor/x/pruefung' }} />);
    expect(html).toMatch(/<button[^>]*>(<span[^>]*>.*?<\/span>)?Prüfen<\/button>/);
    expect(html).not.toContain('aria-label="Prüfung"');
  });

  it('ohne pruefung_url (älteres sales-ui): kein Knopf', () => {
    const html = renderToStaticMarkup(<SeiteApp start={seitenStart()} />);
    expect(html).not.toContain('>Prüfen<');
  });
});
