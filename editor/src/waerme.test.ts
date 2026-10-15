import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import ContainerPropsSchema from './documents/blocks/Container/ContainerPropsSchema';
import { VorlagenImage } from './documents/blocks/Vorlagentext';
import { ImageSchema } from './schemata';

// Paket 1 (Marketing dedee1a1): rundes Bild und randloses Band duerfen beim Bearbeiten nicht verloren gehen.
describe('Waerme: Bildform und Band ueberleben den Editor', () => {
  it('Bild behaelt borderRadius und form', () => {
    const r = ImageSchema.parse({ style: { borderRadius: 16 }, props: { url: '/medien/datei/a.jpg', form: 'kreis' } });
    expect(r.style?.borderRadius).toBe(16);
    expect(r.props?.form).toBe('kreis');
  });
  it('Bild lehnt fremde Form und zu grosse Rundung ab', () => {
    expect(ImageSchema.safeParse({ props: { form: 'stern' } }).success).toBe(false);
    expect(ImageSchema.safeParse({ style: { borderRadius: 40 } }).success).toBe(false);
  });
  it('Container behaelt randlos', () => {
    const r = ContainerPropsSchema.parse({ props: { childrenIds: [], randlos: true } });
    expect(r.props?.randlos).toBe(true);
  });
  it('Vorschau rundet das Bild', () => {
    const kreis = renderToStaticMarkup(React.createElement(VorlagenImage, { props: { url: '/medien/datei/a.jpg', form: 'kreis' } }));
    const rund = renderToStaticMarkup(React.createElement(VorlagenImage, { style: { borderRadius: 12 }, props: { url: '/medien/datei/a.jpg' } }));
    const eckig = renderToStaticMarkup(React.createElement(VorlagenImage, { props: { url: '/medien/datei/a.jpg' } }));
    expect(kreis).toContain('vorlage-rund');
    expect(kreis).toContain('--rund:50%');
    expect(rund).toContain('--rund:12px');
    expect(eckig).not.toContain('vorlage-rund');
  });
});
