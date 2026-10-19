import React from 'react';

import type { ExportAuswahl } from '../chat';
import { useSelectedBlockId } from '../documents/editor/EditorContext';

import ChatLeiste from './Chat/ChatLeiste';

export type Export = (v: ExportAuswahl | null) => void;

const NEWSLETTER_VORSCHLAEGE = ['Mach den Kopf ruhiger', 'Farben aus dem Laden übernehmen', 'Bilder in Medien exportieren'];

// Der Assistent fuer den ganzen Newsletter - im Inspector (Desktop) und im Reiter "Assistent" (Handy).
export default function NewsletterChat({ exportOeffnen, hoehe = 'min(440px, 48vh)' }: { exportOeffnen: Export; hoehe?: string }) {
  const auswahl = useSelectedBlockId();
  return (
    <ChatLeiste kontext={{ fenster: 'newsletter', auswahl }} hoehe={hoehe} vorschlaege={NEWSLETTER_VORSCHLAEGE} onExport={exportOeffnen} />
  );
}
