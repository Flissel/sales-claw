import { describe, expect, it } from 'vitest';

import { ButtonSchema, HeadingSchema, ImageSchema, kursivTeile, schriftFamilie, TextSchema } from './schemata';
import ContainerPropsSchema from './documents/blocks/Container/ContainerPropsSchema';
import EmailLayoutPropsSchema from './documents/blocks/EmailLayout/EmailLayoutPropsSchema';

describe('neue Felder ueberleben das Bearbeiten', () => {
  it('Heading', () => {
    const d = { style: { fontFamily: 'ANZEIGE', letterSpacing: 3, textTransform: 'uppercase', lineHeight: 1.1 },
                props: { text: 'Herbst*brief*', level: 'h1' } };
    expect(HeadingSchema.parse(d)).toEqual(d);
  });
  it('Text', () => {
    const d = { style: { fontFamily: 'TEXT', letterSpacing: -1 }, props: { text: 'x', markdown: true } };
    expect(TextSchema.parse(d)).toEqual(d);
  });
  it('Image', () => {
    const d = { style: {}, props: { url: '/medien/datei/a.jpg', width: 600, height: 300, sw: true, grafik: false } };
    expect(ImageSchema.parse(d)).toEqual(d);
  });
  it('Container', () => {
    const d = { style: { overlay: { farbe: '#2f4858', deckkraft: 86 } },
                props: { childrenIds: ['a'], url: 'medien:kopf.jpg', width: 600, height: 300, grafik: false } };
    expect(ContainerPropsSchema.parse(d)).toEqual(d);
  });
  it('EmailLayout', () => {
    const d = { childrenIds: [], schriften: { anzeige: 'oxanium', text: 'rajdhani' }, dunkel: true,
                rollen: { 'a/data/props/text': 'laden' } };
    expect(EmailLayoutPropsSchema.parse(d)).toEqual(d);
  });
  it('Button behaelt Vorlagenschrift', () => {
    const d = { style: { fontFamily: 'ANZEIGE' }, props: { text: 'Los' } };
    expect(ButtonSchema.parse(d)).toEqual(d);
  });
  it('lehnt Unsinn ab', () => {
    expect(HeadingSchema.safeParse({ style: { letterSpacing: 99 }, props: {} }).success).toBe(false);
    expect(EmailLayoutPropsSchema.safeParse({ schriften: { anzeige: 'comic' } }).success).toBe(false);
  });
});

describe('Darstellung im Editor', () => {
  const paar = { anzeige: 'oxanium', text: 'rajdhani' } as const;
  it('ANZEIGE/TEXT nehmen das Schriftpaar der Vorlage', () => {
    expect(schriftFamilie('ANZEIGE', paar)).toBe("Oxanium, 'Trebuchet MS', Arial, sans-serif");
    expect(schriftFamilie('TEXT', paar)).toBe("Rajdhani, 'Arial Narrow', Arial, sans-serif");
  });
  it('ohne Schriftpaar erbt der Block (undefined), alte Schluessel bleiben', () => {
    expect(schriftFamilie('ANZEIGE', null)).toBeUndefined();
    expect(schriftFamilie('TEXT', { anzeige: 'bodoni' })).toBeUndefined();
    expect(schriftFamilie('MONOSPACE', paar)).toContain('monospace');
    expect(schriftFamilie(null, paar)).toBeUndefined();
  });
  it('*kursiv* in Ueberschriften', () => {
    expect(kursivTeile('Herbst*brief*')).toEqual([
      { text: 'Herbst', kursiv: false },
      { text: 'brief', kursiv: true },
    ]);
    expect(kursivTeile('Der *Radhaus* Rundbrief')).toEqual([
      { text: 'Der ', kursiv: false },
      { text: 'Radhaus', kursiv: true },
      { text: ' Rundbrief', kursiv: false },
    ]);
    expect(kursivTeile('5 * 3 = 15')).toEqual([{ text: '5 * 3 = 15', kursiv: false }]);
    expect(kursivTeile('')).toEqual([]);
  });
});
