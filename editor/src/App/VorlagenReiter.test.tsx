import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Start } from '../pult';

import {
  alsNeuAusfuehren,
  anwendenAusfuehren,
  AnwendenFrage,
  anwendenSperre,
  anwendenText,
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

const VORLAGEN = [
  { name: 'klassik', beschreibung: 'Ruhig und klar, mit großem Kopfbild', fassung: 3 },
  { name: 'studio', beschreibung: 'Dunkel und kräftig', fassung: 1 },
];

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

  it('„Anwenden“ und „Als neuer Entwurf“ sind bei nurLesen gesperrt', () => {
    expect(anwendenSperre(false, true)).toBe('Liegt zur Freigabe – erst zurückziehen');
    const html = liste({ nurLesen: true });
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Auf diesen Entwurf anwenden …/);
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

  it('Ablehnung bleibt im Dialog', async () => {
    const fenster = fensterFaelschen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort(422, { grund: 'Unbekannte Vorlage' })));
    expect(await alsNeuAusfuehren(start, 'studio', 'Herbstpost')).toBe('Unbekannte Vorlage');
    expect(fenster.href).toBe('/marketing/editor/' + IID);
  });
});
