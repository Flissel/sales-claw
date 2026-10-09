import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { GedankenAufklapp, GedankenLive } from './Gedanken';

const live = { schritt: '', schritt_nr: 0, zwischenstand: null, stopp: null,
  denken: 'Let me think', schritte: [{ zeit: '08:03:41', text: 'Frage an Claude' }] };

describe('GedankenLive', () => {
  it('zeigt Denken und Schritte, wenn sichtbar', () => {
    const html = renderToStaticMarkup(<GedankenLive live={live} sichtbar umschalten={() => {}} />);
    expect(html).toContain('Denkt nach …');
    expect(html).toContain('Let me think');
    expect(html).toContain('Frage an Claude');
    expect(html).toContain('Gedanken ausblenden');
  });
  it('ausgeblendet: nur der Schalter', () => {
    const html = renderToStaticMarkup(<GedankenLive live={live} sichtbar={false} umschalten={() => {}} />);
    expect(html).toContain('Gedanken einblenden');
    expect(html).not.toContain('Let me think');
  });
  it('rendert nichts ohne Spur', () => {
    const leer = { ...live, denken: '', schritte: [] };
    expect(renderToStaticMarkup(<GedankenLive live={leer} sichtbar umschalten={() => {}} />)).toBe('');
  });
});

describe('GedankenAufklapp', () => {
  it('zugeklappt mit Titel, Kennung erst aufgeklappt', () => {
    const html = renderToStaticMarkup(<GedankenAufklapp denken="Let me think" schritte={live.schritte} />);
    expect(html).toContain('Gedanken &amp; Schritte');
    expect(html).not.toContain('Let me think');
  });
  it('rendert nichts ohne Spur', () => {
    expect(renderToStaticMarkup(<GedankenAufklapp denken="" schritte={[]} />)).toBe('');
  });
});
