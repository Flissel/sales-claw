import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { VorlagenHeading, VorlagenImage, VorlagenText } from './documents/blocks/Vorlagentext';

describe('Darstellung der Vorlagenfelder im Canvas', () => {
  it('Ueberschrift: *kursiv* als <em>, Laufweite und Versalien', () => {
    const html = renderToStaticMarkup(
      React.createElement(VorlagenHeading, {
        style: { letterSpacing: 2, textTransform: 'uppercase', lineHeight: 1.1 },
        props: { text: 'Herbst*brief*', level: 'h2' },
      })
    );
    expect(html).toContain('<h2');
    expect(html).toContain('Herbst<em>brief</em>');
    expect(html).toContain('letter-spacing:2px');
    expect(html).toContain('text-transform:uppercase');
    expect(html).toContain('line-height:1.1');
  });
  it('Text: Paket-Text erbt die Feinheiten vom Wrapper', () => {
    const html = renderToStaticMarkup(
      React.createElement(VorlagenText, { style: { letterSpacing: -1 }, props: { text: 'hallo' } })
    );
    expect(html).toContain('letter-spacing:-1px');
    expect(html).toContain('hallo');
  });
  it('Bild: Schwarz-weiss nur mit sw', () => {
    const an = renderToStaticMarkup(React.createElement(VorlagenImage, { props: { url: '/medien/datei/a.jpg', sw: true } }));
    const aus = renderToStaticMarkup(React.createElement(VorlagenImage, { props: { url: '/medien/datei/a.jpg' } }));
    expect(an).toContain('class="vorlage-sw"');
    expect(aus).not.toContain('vorlage-sw');
  });
});
