import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import HandyApp, { HandyAnsicht } from './HandyApp';

const IID = 'b12c46b9-8f87-412b-b2e7-7215b354a75b';
const start = { vorschau_url: `/marketing/entwurf/${IID}/vorschau`, zurueck_url: `/marketing/entwurf/${IID}` };

describe('HandyAnsicht', () => {
  it('zeigt zwei Reiter und die gesandboxte Handy-Vorschau der Basisfassung', () => {
    const html = renderToStaticMarkup(<HandyAnsicht start={start} basis={4} betreff="Oktober" />);
    expect(html).toContain('Vorschau');
    expect(html).toContain('Assistent');
    expect(html).toContain('sandbox=""');
    expect(html).toContain('fassung=4&amp;format=handy');
    expect(html).toContain(`href="/marketing/entwurf/${IID}"`);
    expect(html).toContain('Zurück');
    expect(html).toContain('Oktober');
    // Kein Bearbeiten am Handy: kein Chat im Vorschau-Reiter.
    expect(html).not.toContain('Nachricht an den Assistenten');
  });

  it('zeigt im Reiter Assistent den Chat statt der Vorschau', () => {
    const html = renderToStaticMarkup(<HandyAnsicht start={start} basis={4} betreff="" reiter="assistent" />);
    expect(html).toContain('Nachricht an den Assistenten');
    expect(html).not.toContain('sandbox=""');
  });
});

describe('HandyApp', () => {
  it('liest den Pult-Zustand und rendert ohne Start nur Kopf und Reiter', () => {
    const html = renderToStaticMarkup(<HandyApp />);
    expect(html).toContain('Vorschau');
    expect(html).toContain('Newsletter');
    expect(html).not.toContain('<iframe');
    expect(renderToStaticMarkup(<HandyApp reiter="assistent" />)).toContain('Nachricht an den Assistenten');
  });
});
