import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { Seite } from '../../seite';

import SeitenFuss, { IMPRESSUM_FEHLT, fussFarbe } from './SeitenFuss';

const SEITE = {
  breite: 600, hoehe: 700, hintergrund: { farbe: '#ffffff', bild: null },
  schriften: { anzeige: 'dm-sans', text: 'dm-sans' }, ebenen: [],
} as unknown as Seite;

describe('SeitenFuss', () => {
  it('zeigt Impressum, Vermittlerangaben und Abmeldehinweis wie die Vorschau', () => {
    const html = renderToStaticMarkup(
      <SeitenFuss s={SEITE} zoom={1} p={{ impressum: 'Felix Baumann\nMünchen', vermittlerangaben: '§34f',
                                          abmelde_hinweis: 'Abmelden: {abmeldelink}' }} />);
    expect(html).toContain('aria-label="Impressum (fest, aus der Marke)"');
    expect(html).toContain('Felix Baumann\nMünchen');
    expect(html).toContain('§34f');
    expect(html).toContain('Abmelden: [Abmeldelink]');
    expect(html).toContain('white-space:pre-line');
  });

  it('meldet ein fehlendes Impressum rot', () => {
    const html = renderToStaticMarkup(
      <SeitenFuss s={SEITE} zoom={1} p={{ impressum: ' ', vermittlerangaben: '', abmelde_hinweis: '' }} />);
    expect(html).toContain(IMPRESSUM_FEHLT);
  });

  it('Farbe wie seite_html: grau auf hell, weiss auf dunkel', () => {
    expect(fussFarbe('#ffffff')).toBe('#666666');
    expect(fussFarbe('#101018')).toBe('#ffffff');
    expect(fussFarbe('kaputt')).toBe('#666666');
  });
});
