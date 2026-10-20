// Seitenmodell der freien Collagen-Flaeche (Spiegel von claw/seite.py und seite_html.py, Stufe 1).
import type { CSSProperties } from 'react';
import { neueId } from './gestaltung';
import { SCHRIFT_FAMILIE } from './schemata';

export const BREITE = 600;
export const HOEHE_MIN = 400;
export const HOEHE_MAX = 6000;
export const MAX_EBENEN = 80;
export const MAX_TEXT = 3000;

// Mail-sichere Stapel, woertlich aus claw/schriften.py.
export const MAIL_STAPEL: Record<string, string> = {
  cormorant: "Georgia, 'Times New Roman', serif",
  'dm-sans': 'Arial, Helvetica, sans-serif',
  playfair: "Georgia, 'Times New Roman', serif",
  poppins: 'Arial, Helvetica, sans-serif',
  'young-serif': 'Georgia, serif',
  manrope: 'Arial, Helvetica, sans-serif',
  bodoni: 'Didot, Georgia, serif',
  montserrat: 'Arial, Helvetica, sans-serif',
  josefin: "'Trebuchet MS', Arial, sans-serif",
  oxanium: "'Trebuchet MS', Arial, sans-serif",
  rajdhani: "'Arial Narrow', Arial, sans-serif",
};

export type Rolle = 'ANZEIGE' | 'TEXT' | 'HAND';

interface Grund {
  id: string;
  x: number;
  y: number;
  breite: number;
  hoehe: number;
  drehung?: number;
  deckkraft?: number;
}

export interface BildEbeneS extends Grund {
  art: 'bild';
  quelle: string;
  passung?: 'fuellen' | 'einpassen';
  rundung?: number;
  kreis?: boolean;
  rahmen_breite?: number;
  rahmen_farbe?: string;
  schatten?: boolean;
}

export interface TextEbeneS extends Grund {
  art: 'text';
  text: string;
  rolle: Rolle;
  gewicht?: number;
  groesse: number;
  zeilenabstand?: number;
  buchstabenabstand?: number;
  farbe: string;
  ausrichtung?: 'links' | 'mitte' | 'rechts';
  grossbuchstaben?: boolean;
  kursiv?: boolean;
  hintergrund?: string | null;
}

export interface FormEbeneS extends Grund {
  art: 'form';
  form: 'rechteck' | 'kreis';
  farbe: string;
  rundung?: number;
}

export interface KnopfEbeneS extends Grund {
  art: 'knopf';
  text: string;
  link: string;
  farbe: string;
  textfarbe: string;
  rundung?: number;
  rolle?: 'ANZEIGE' | 'TEXT';
  groesse?: number;
  gewicht?: number;
}

export type SeitenEbene = BildEbeneS | TextEbeneS | FormEbeneS | KnopfEbeneS;

export interface Seite {
  version: 1;
  breite: number;
  hoehe: number;
  hintergrund: { farbe: string; bild: string | null };
  schriften: { anzeige: string; text: string };
  ebenen: SeitenEbene[];
}

const RUECKFALL = 'dm-sans';

/** Schriftfamilie je Rolle. TEXT ist nur der mail-sichere Stapel, nie die Webschrift. */
export function familieFuer(rolle: Rolle, s: Seite): string {
  if (rolle === 'HAND') return SCHRIFT_FAMILIE.caveat;
  const gewaehlt = rolle === 'ANZEIGE' ? s.schriften.anzeige : s.schriften.text;
  const id = Object.prototype.hasOwnProperty.call(MAIL_STAPEL, gewaehlt) ? gewaehlt : RUECKFALL;
  if (rolle === 'TEXT') return MAIL_STAPEL[id];
  return SCHRIFT_FAMILIE[id];
}

export function neueEbene(art: SeitenEbene['art'], s: Seite, quelle?: string): SeitenEbene {
  const id = neueId(s.ebenen.map((e) => e.id));
  const mitte = { id, x: BREITE / 2, y: Math.round(s.hoehe / 2), drehung: 0, deckkraft: 1 };
  switch (art) {
    case 'bild':
      return { ...mitte, art, quelle: quelle ?? '', breite: 280, hoehe: 200, passung: 'fuellen', rundung: 0,
        kreis: false, rahmen_breite: 0, rahmen_farbe: '#ffffff', schatten: false };
    case 'text':
      return { ...mitte, art, text: 'Neuer Text', rolle: 'TEXT', gewicht: 400, groesse: 17, zeilenabstand: 1.3,
        buchstabenabstand: 0, farbe: '#333333', ausrichtung: 'links', grossbuchstaben: false, kursiv: false,
        hintergrund: null, breite: 400, hoehe: 60 };
    case 'form':
      return { ...mitte, art, form: 'rechteck', farbe: '#5b3fd6', rundung: 0, breite: 200, hoehe: 120 };
    case 'knopf':
      return { ...mitte, art, text: 'Mehr erfahren', link: 'https://example.com', farbe: '#5b3fd6',
        textfarbe: '#ffffff', rundung: 6, rolle: 'TEXT', groesse: 16, gewicht: 600, breite: 220, hoehe: 48 };
  }
}

const TEXTLINK = /\[[^\]]*\]\(([^)]*)\)/g;
export const HTTPS = /^https:\/\/[^\s"'<>]+$/;
const ANREDE = '{vorname}';
const QUELLE = /^medien:[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.(png|jpe?g|gif|webp)$/;

function laenge(t: string): number {
  return [...t].length;
}

/** Deutscher Grund, warum die Seite nicht gespeichert werden darf, sonst null (Meldungen wie seite.py). */
export function speicherGrund(s: Seite): string | null {
  if (s.ebenen.length > MAX_EBENEN) return `Seite: höchstens ${MAX_EBENEN} Ebenen`;
  for (let i = 0; i < s.ebenen.length; i++) {
    const e = s.ebenen[i];
    const kontext = `Ebene ${i + 1}`;
    if (e.art === 'text') {
      if (laenge(e.text) < 1 || laenge(e.text) > MAX_TEXT) {
        return `${kontext} text: Text mit 1 bis ${MAX_TEXT} Zeichen erwartet`;
      }
      const fliess = e.rolle === 'TEXT' && (e.drehung ?? 0) === 0;
      if (e.text.includes(ANREDE) && !fliess) {
        return `${kontext}: Die Anrede ${ANREDE} geht nur in Fließtext (Rolle TEXT, nicht gedreht)`;
      }
      const ziele = [...e.text.matchAll(TEXTLINK)].map((m) => m[1]);
      if (ziele.length > 0 && !fliess) {
        return `${kontext}: Links im Text gehen nur in Fließtext (Rolle TEXT, nicht gedreht)`;
      }
      if (ziele.some((z) => !HTTPS.test(z))) return `${kontext} Link: nur https://-Links erlaubt`;
    } else if (e.art === 'bild') {
      if (!QUELLE.test(e.quelle) || e.quelle.includes('..')) {
        return `${kontext} quelle: nur Bilder aus der Mediathek (medien:…) erlaubt`;
      }
    } else if (e.art === 'knopf') {
      if (laenge(e.text) < 1 || laenge(e.text) > 60) return `${kontext} text: Text mit 1 bis 60 Zeichen erwartet`;
      if (!HTTPS.test(e.link)) return `${kontext} link: nur https://-Links erlaubt`;
    }
  }
  return null;
}

/** Platzierung wie seite_html._lage: ohne Inhalt, Mittelpunkt x/y. */
export function ebenenStil(e: SeitenEbene): CSSProperties {
  const stil: CSSProperties = {
    position: 'absolute',
    left: e.x - e.breite / 2,
    top: e.y - e.hoehe / 2,
    width: e.breite,
  };
  if (e.art === 'text') stil.minHeight = e.hoehe;
  else stil.height = e.hoehe;
  if (e.drehung) stil.transform = `rotate(${e.drehung}deg)`;
  if (e.deckkraft !== undefined && e.deckkraft !== 1) stil.opacity = e.deckkraft;
  return stil;
}
