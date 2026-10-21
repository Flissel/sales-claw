import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Start, type VorlageInfo } from '../pult';

import {
  alsNeuAusfuehren,
  alsNeuSperre,
  neuDialogNach,
  vorlageLabel,
  anwendenAusfuehren,
  AnwendenFrage,
  AngelegtHinweis,
  anwendenSperre,
  anwendenText,
  NUR_ANWENDEN,
  titelFehler,
  VorlagenListe,
} from './VorlagenReiter';

const IID = 'b12c46b9-8f87-412b-b2e7-7215b354a75b';
const start = {
  csrf: 'marke-1',
  vorlagen_url: `/marketing/editor/${IID}/vorlagen.json`,
  vorlage_bild_url: `/marketing/editor/${IID}/vorlage-bild/`,
  vorlage_url: `/marketing/editor/${IID}/vorlage`,
} as Start;

const VORLAGEN: VorlageInfo[] = [
  { name: 'klassik', beschreibung: 'Ruhig und klar, mit großem Kopfbild', fassung: 3, format: 'bloecke', neu: true },
  { name: 'studio', beschreibung: 'Dunkel und kräftig', fassung: 1, format: 'bloecke', neu: true },
];
const COLLAGE: VorlageInfo = { name: 'split', beschreibung: 'Split mit Bild', fassung: 2, format: 'seite', neu: true };

function antwort(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function fensterFaelschen() {
  const reload = vi.fn();
  const location = { reload, href: '/marketing/editor/' + IID };
  vi.stubGlobal('window', { location });
  return location;
}

const leer = () => undefined;
const liste = (teil: Partial<React.ComponentProps<typeof VorlagenListe>> = {}) =>
  renderToStaticMarkup(
    <VorlagenListe
      start={start}
      vorlagen={VORLAGEN}
      ungespeichert={false}
      nurLesen={false}
      onAnwenden={leer}
      onAlsNeu={leer}
      onNeuLaden={leer}
      {...teil}
    />,
  );

afterEach(() => vi.unstubAllGlobals());

describe('Reiter Vorlagen', () => {
  it('zeigt je Vorlage Beschreibung und gesandboxten Rahmen mit vorlage_bild_url + name', () => {
    const html = liste();
    expect(html).toContain('Ruhig und klar, mit großem Kopfbild');
    expect(html).toContain('Dunkel und kräftig');
    expect(html).toContain(`src="/marketing/editor/${IID}/vorlage-bild/klassik"`);
    expect(html).toContain(`src="/marketing/editor/${IID}/vorlage-bild/studio"`);
    expect((html.match(/<iframe[^>]*sandbox=""/g) ?? []).length).toBe(2);
    expect(html).toContain('loading="lazy"');
    expect(html).toContain('tabindex="-1"');
    expect(html).toContain('Als neuer Entwurf');
    expect(html).toContain('Auf diesen Entwurf anwenden …');
  });

  it('„Anwenden“ ist bei ungespeicherten Änderungen gesperrt (Erst speichern)', () => {
    expect(anwendenSperre(true, false)).toBe('Erst speichern');
    const html = liste({ ungespeichert: true });
    expect(html).toContain('Erst speichern');
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Auf diesen Entwurf anwenden …/);
  });

  it('nurLesen sperrt „Anwenden“, „Als neuer Entwurf“ bleibt (berührt den eingereichten nicht)', () => {
    expect(anwendenSperre(false, true)).toBe('Liegt zur Freigabe – erst zurückziehen');
    expect(alsNeuSperre(false)).toBeNull();
    const html = liste({ nurLesen: true });
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Auf diesen Entwurf anwenden …/);
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Als neuer Entwurf/);
    expect(html).toMatch(/<button[^>]*>Als neuer Entwurf/);
  });

  it('ungespeicherte Änderungen sperren auch „Als neuer Entwurf“ (Erst speichern)', () => {
    expect(alsNeuSperre(true)).toBe('Erst speichern');
    const html = liste({ ungespeichert: true });
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Als neuer Entwurf/);
    expect(liste()).not.toMatch(/<button[^>]*disabled=""[^>]*>Als neuer Entwurf/);
  });

  it('Karte und Dialog zeigen denselben Namen (Label statt Schlüssel)', () => {
    expect(vorlageLabel('klassik')).toBe('Klassik');
    expect(vorlageLabel('bild-kopf')).toBe('Bild kopf');
    expect(liste()).toContain('>Klassik<');
    expect(renderToStaticMarkup(<AnwendenFrage name="klassik" basis={7} grund={null} />)).toContain('„Klassik“');
  });

  it('frei ohne ungespeicherte Änderungen und ohne nurLesen', () => {
    expect(anwendenSperre(false, false)).toBeNull();
    expect(liste()).not.toMatch(/<button[^>]*disabled=""[^>]*>Auf diesen Entwurf anwenden …/);
  });

  it('ohne Vorlagen-Adresse: nicht eingerichtet', () => {
    const html = liste({ start: { csrf: 'x' } as Start, vorlagen: null });
    expect(html).toContain('Vorlagen sind hier noch nicht eingerichtet');
  });

  it('nicht erreichbar und leer haben eigene Texte', () => {
    expect(liste({ vorlagen: null })).toContain('Vorlagen gerade nicht erreichbar');
    expect(liste({ vorlagen: [] })).toContain('Keine freigegebenen Vorlagen');
    expect(liste({ vorlagen: 'laedt' })).toContain('Vorlagen werden geladen');
  });
});

describe('Vorlage anwenden', () => {
  it('Bestätigung nennt, was ersetzt wird und dass die Fassung bleibt', () => {
    expect(anwendenText(7)).toBe(
      'Aufbau, Gestaltung, Texte und Bilder werden ersetzt. Betreff und Vorschautext bleiben. Deine Fassung 7 bleibt im Verlauf.',
    );
    const html = renderToStaticMarkup(<AnwendenFrage name="klassik" basis={7} grund={null} />);
    expect(html).toContain('Deine Fassung 7 bleibt im Verlauf.');
  });

  it('Ablehnung (Assistent arbeitet) zeigt den Grund im Dialog und lädt nicht neu', async () => {
    const fenster = fensterFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Der Assistent arbeitet gerade' })));
    const grund = await anwendenAusfuehren(start, 'klassik', 7);
    expect(grund).toBe('Der Assistent arbeitet gerade');
    expect(fenster.reload).not.toHaveBeenCalled();
    const html = renderToStaticMarkup(<AnwendenFrage name="klassik" basis={7} grund={grund} />);
    expect(html).toContain('Der Assistent arbeitet gerade');
  });

  it('veraltete Basis (Agent-Fassung neuer) zeigt den Grund und lädt nicht neu', async () => {
    const fenster = fensterFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Inzwischen gibt es Fassung 9' })));
    expect(await anwendenAusfuehren(start, 'klassik', 7)).toBe('Inzwischen gibt es Fassung 9');
    expect(fenster.reload).not.toHaveBeenCalled();
  });

  it('Erfolg lädt neu', async () => {
    const fenster = fensterFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { fassung: 8 })));
    expect(await anwendenAusfuehren(start, 'klassik', 7)).toBeNull();
    expect(fenster.reload).toHaveBeenCalledTimes(1);
  });
});

describe('Als neuer Entwurf', () => {
  it('verlangt einen Titel mit 1 bis 200 Zeichen', () => {
    expect(titelFehler('')).toBe('Bitte einen Titel eingeben');
    expect(titelFehler('   ')).toBe('Bitte einen Titel eingeben');
    expect(titelFehler('x'.repeat(200))).toBeNull();
    expect(titelFehler('x'.repeat(201))).toBe('Höchstens 200 Zeichen');
    expect(titelFehler('Herbstpost')).toBeNull();
  });

  it('ohne Titel keine Anfrage', async () => {
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    fensterFaelschen();
    expect(await alsNeuAusfuehren(start, 'studio', ' ')).toBe('Bitte einen Titel eingeben');
    expect(f).not.toHaveBeenCalled();
  });

  it('Erfolg öffnet den neuen Entwurf', async () => {
    const fenster = fensterFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { editor_url: '/marketing/editor/neu-1' })));
    expect(await alsNeuAusfuehren(start, 'studio', 'Herbstpost')).toBeNull();
    expect(fenster.href).toBe('/marketing/editor/neu-1');
  });

  it('Dialog hängt nie auf „Wird angelegt …“: Erfolg schließt ihn, Fehler gibt ihn frei', async () => {
    const fenster = fensterFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { editor_url: '/marketing/editor/neu-1' })));
    const offen = { name: 'studio', titel: 'Herbstpost', grund: null, laeuft: true };
    // Erfolg: Navigation angestossen, Dialog zu (bleibt die Seite, etwa nach der Verlassen-Warnung, ist nichts gesperrt).
    expect(await neuDialogNach(start, offen)).toBeNull();
    expect(fenster.href).toBe('/marketing/editor/neu-1');
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Unbekannte Vorlage' })));
    expect(await neuDialogNach(start, offen)).toEqual({ ...offen, grund: 'Unbekannte Vorlage', laeuft: false });
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new Error('x'))));
    expect(await neuDialogNach(start, offen)).toMatchObject({ laeuft: false, grund: 'Keine Verbindung zum Pult' });
  });

  it('Ablehnung bleibt im Dialog', async () => {
    const fenster = fensterFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Unbekannte Vorlage' })));
    expect(await alsNeuAusfuehren(start, 'studio', 'Herbstpost')).toBe('Unbekannte Vorlage');
    expect(fenster.href).toBe('/marketing/editor/' + IID);
  });
});

describe('Reiter Vorlagen: Collage-Vorlagen (Stufe 5)', () => {
  it('Collage-Vorlage: Seitenvorschau, nur „Als neuer Entwurf“, kein Anwenden auf Blöcke', () => {
    const html = liste({ vorlagen: [COLLAGE] });
    expect(html).toContain(`src="/marketing/editor/${IID}/vorlage-bild/split?format=seite"`);
    expect(html).toContain('Collage-Vorlage');
    expect(html).toContain('Als neuer Entwurf');
    expect(html).not.toContain('Auf diesen Entwurf anwenden');
  });

  it('Block-Vorlage behält die Mail-Vorschau ohne Format', () => {
    const html = liste({ vorlagen: [VORLAGEN[0]] });
    expect(html).toContain(`src="/marketing/editor/${IID}/vorlage-bild/klassik"`);
    expect(html).not.toContain('format=seite');
  });

  it('Anlegen mit Warnungen: nicht weiter, der Dialog zeigt die Hinweise', async () => {
    const fenster = fensterFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(200, { editor_url: '/marketing/editor/neu-1', warnungen: ['Logo fehlt'] })));
    const offen = { name: 'split', titel: 'Herbst', grund: null, laeuft: true };
    expect(await neuDialogNach(start, offen)).toEqual({
      ...offen,
      laeuft: false,
      angelegt: { editorUrl: '/marketing/editor/neu-1', warnungen: ['Logo fehlt'] },
    });
    expect(fenster.href).toBe('/marketing/editor/' + IID);
  });

  it('Hinweis nach dem Anlegen: Warnungen und Verweis in den Editor', () => {
    const html = renderToStaticMarkup(<AngelegtHinweis warnungen={['Logo <fehlt>', 'Bild für motiv1 fehlt']} />);
    expect(html).toContain('Logo &lt;fehlt&gt;');
    expect(html).toContain('Bild für motiv1 fehlt');
    expect(html).toContain('ist angelegt');
  });
});

describe('Reiter Vorlagen: nur noch Collagen (Gesamtprüfung Stufe 5)', () => {
  const BLOCK_NUR_ANWENDEN: VorlageInfo = { ...VORLAGEN[0], neu: false };

  it('mit freigegebener Collage-Vorlage bleibt die Block-Vorlage zum Anwenden, nur „Als neuer Entwurf“ fehlt', () => {
    const html = liste({ vorlagen: [COLLAGE, BLOCK_NUR_ANWENDEN] });
    const block = html.slice(html.indexOf('>Klassik<'));
    expect(block).toContain('Auf diesen Entwurf anwenden …');
    expect(block).not.toContain('Als neuer Entwurf');
    expect(block).toContain(NUR_ANWENDEN);
    // die Collage-Vorlage davor bietet weiter „Als neuer Entwurf“
    expect(html.slice(0, html.indexOf('>Klassik<'))).toContain('Als neuer Entwurf');
    expect(html.match(/Als neuer Entwurf/g)?.length).toBe(1);
  });

  it('Block-Vorlage mit neu behält beide Wege und keinen Hinweis', () => {
    const html = liste({ vorlagen: [VORLAGEN[0]] });
    expect(html).toContain('Als neuer Entwurf');
    expect(html).toContain('Auf diesen Entwurf anwenden …');
    expect(html).not.toContain(NUR_ANWENDEN);
  });

  it('Anwenden-Sperren gelten auch für Block-Vorlagen ohne „neu“', () => {
    expect(liste({ vorlagen: [BLOCK_NUR_ANWENDEN], ungespeichert: true })).toMatch(
      /<button[^>]*disabled=""[^>]*>Auf diesen Entwurf anwenden …/,
    );
  });
});
