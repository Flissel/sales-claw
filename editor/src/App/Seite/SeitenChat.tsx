// Assistent im Collage-Editor (Freie Fläche Stufe 3): der Chat mit kontext {fenster: 'seite'}. Die gewaehlte
// Ebene geht von selbst mit (seitenKontext) und wird zusaetzlich als Chip angeboten - zum Anhaengen weiterer
// Ebenen (art 'ebene' ohne flaeche, Kurzname aus Art und Textanfang).
import React, { useMemo } from 'react';

import { seitenChip } from '../../chatKontext';
import type { SeitenEbene } from '../../seite';
import { seitenKontext } from '../../seiteChat';
import ChatLeiste from '../Chat/ChatLeiste';

const SEITE_VORSCHLAEGE = ['Mach den Aufmacher größer', 'Mehr Weißraum', 'Farben aus der Marke übernehmen'];
const KEIN_EXPORT = () => undefined;

export default function SeitenChat({ ebene, hoehe = 'min(360px, 45vh)' }: { ebene: SeitenEbene | null; hoehe?: string }) {
  const angebot = useMemo(() => (ebene ? seitenChip(ebene) : null), [ebene]);
  const kontext = useMemo(() => seitenKontext(ebene), [ebene]);
  return (
    <ChatLeiste kontext={kontext} hoehe={hoehe} vorschlaege={SEITE_VORSCHLAEGE} onExport={KEIN_EXPORT} angebot={angebot} />
  );
}
