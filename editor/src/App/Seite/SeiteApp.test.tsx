import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { Start } from '../../pult';
import type { Seite } from '../../seite';

import SeiteApp, { ASSISTENT_HINWEIS } from './SeiteApp';

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

  it('zeigt den Hinweis zum Assistenten, aber weder Assistent noch Einreichen', () => {
    expect(ASSISTENT_HINWEIS).toBe('Der Assistent kommt für Collage-Newsletter in der nächsten Stufe.');
    expect(html).toContain(ASSISTENT_HINWEIS);
    expect(html).not.toContain('Nachricht an den Assistenten');
    expect(html).not.toContain('einreichen');
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
