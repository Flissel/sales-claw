// Aussehen einer Collagen-Ebene wie seite_html._ebene (Vorschau und PDF): Lage aus ebenenStil,
// dazu z-index, box-sizing:border-box und die Regeln je Art. Vorgaben wie seite.py (_ART), falls
// ein Feld im Dokument fehlt.
import type { CSSProperties } from 'react';

import { ebenenStil, familieFuer, type Seite, type SeitenEbene, type TextEbeneS, type KnopfEbeneS } from '../../seite';
import { quelleAnzeige } from '../Gestaltung/hilfen';

const AUSRICHTUNG = { links: 'left', mitte: 'center', rechts: 'right' } as const;

export function aussehen(s: Seite, e: SeitenEbene, z: number): CSSProperties {
  const stil: CSSProperties = { ...ebenenStil(e), zIndex: z, boxSizing: 'border-box' };
  if (e.art === 'bild') {
    stil.overflow = 'hidden';
    if (e.kreis) stil.borderRadius = '50%';
    else if (e.rundung) stil.borderRadius = e.rundung;
    if (e.rahmen_breite) stil.border = `${e.rahmen_breite}px solid ${e.rahmen_farbe ?? '#ffffff'}`;
    if (e.schatten) stil.boxShadow = '0 4px 14px rgba(0,0,0,0.3)';
    return stil;
  }
  if (e.art === 'form') {
    stil.background = e.farbe;
    if (e.form === 'kreis') stil.borderRadius = '50%';
    else if (e.rundung) stil.borderRadius = e.rundung;
    return stil;
  }
  if (e.art === 'knopf') return { ...stil, ...knopfSchrift(s, e) };
  return { ...stil, ...textSchrift(s, e) };
}

/** Schrift und Farben eines Knopfs (auch fuer das Textfeld beim Bearbeiten). */
export function knopfSchrift(s: Seite, e: KnopfEbeneS): CSSProperties {
  return {
    background: e.farbe,
    color: e.textfarbe,
    borderRadius: e.rundung ?? 6,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    textAlign: 'center',
    textDecoration: 'none',
    fontFamily: familieFuer(e.rolle ?? 'TEXT', s),
    fontSize: e.groesse ?? 16,
    fontWeight: e.gewicht ?? 600,
  };
}

/** Schrift eines Textes (auch fuer das Textfeld beim Bearbeiten). */
export function textSchrift(s: Seite, e: TextEbeneS): CSSProperties {
  const stil: CSSProperties = {
    fontFamily: familieFuer(e.rolle, s),
    fontSize: e.groesse,
    fontWeight: e.gewicht ?? 400,
    lineHeight: e.zeilenabstand ?? 1.3,
    letterSpacing: `${e.buchstabenabstand ?? 0}em`,
    color: e.farbe,
    textAlign: AUSRICHTUNG[e.ausrichtung ?? 'links'],
    overflowWrap: 'break-word',
  };
  if (e.grossbuchstaben) stil.textTransform = 'uppercase';
  if (e.kursiv) stil.fontStyle = 'italic';
  if (e.hintergrund) stil.background = e.hintergrund;
  return stil;
}

export function bildPassung(e: SeitenEbene): CSSProperties {
  return {
    display: 'block',
    width: '100%',
    height: '100%',
    objectFit: e.art === 'bild' && e.passung === 'einpassen' ? 'contain' : 'cover',
  };
}

/** Seitencontainer wie seite_html.html: 600 breit, Hoehe der Seite, Anschnitt, Hintergrund. */
export function seitenStil(s: Seite): CSSProperties {
  const stil: CSSProperties = {
    position: 'relative',
    width: s.breite,
    height: s.hoehe,
    overflow: 'hidden',
    backgroundColor: s.hintergrund.farbe,
  };
  if (s.hintergrund.bild) {
    stil.backgroundImage = `url('${quelleAnzeige(s.hintergrund.bild)}')`;
    stil.backgroundSize = 'cover';
    stil.backgroundPosition = 'center';
  }
  return stil;
}

/** Farben der Seite fuer das Farbfeld (Benutzt). */
export function seitenFarben(s: Seite): string[] {
  const f = [s.hintergrund.farbe];
  for (const e of s.ebenen) {
    if (e.art === 'form') f.push(e.farbe);
    else if (e.art === 'text') f.push(e.farbe, ...(e.hintergrund ? [e.hintergrund] : []));
    else if (e.art === 'knopf') f.push(e.farbe, e.textfarbe);
    else if (e.rahmen_breite) f.push(e.rahmen_farbe ?? '#ffffff');
  }
  return [...new Set(f.map((x) => x.toUpperCase()))];
}
