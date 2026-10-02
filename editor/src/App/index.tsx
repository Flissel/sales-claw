import React, { useState } from 'react';

import { Stack, useTheme } from '@mui/material';

import type { ExportAuswahl } from '../chat';
import { useInspectorDrawerOpen, useSelectedBlockId } from '../documents/editor/EditorContext';
import { pultStore } from '../pultZustand';

import AbschnittLeiste, { ABSCHNITT_LEISTE_BREITE } from './AbschnittLeiste';
import ChatLeiste from './Chat/ChatLeiste';
import { SperrSchicht, useAgentArbeitet } from './Chat/Sperre';
import ExportDialog from './Export/ExportDialog';
import GestaltungFenster from './Gestaltung/GestaltungFenster';
import InspectorDrawer, { INSPECTOR_DRAWER_WIDTH } from './InspectorDrawer';
import { PULT_LEISTE_HOEHE } from './PultLeiste';
import TemplatePanel from './TemplatePanel';

function useDrawerTransition(cssProperty: 'margin-left' | 'margin-right', open: boolean) {
  const { transitions } = useTheme();
  return transitions.create(cssProperty, {
    easing: !open ? transitions.easing.sharp : transitions.easing.easeOut,
    duration: !open ? transitions.duration.leavingScreen : transitions.duration.enteringScreen,
  });
}

type Export = (v: ExportAuswahl | null) => void;

const NEWSLETTER_VORSCHLAEGE = ['Mach den Kopf ruhiger', 'Farben aus dem Laden übernehmen', 'Bilder in Medien exportieren'];
const FLAECHE_VORSCHLAEGE = ['Titel größer und mittig', 'Mehr Weißraum', 'Text gut lesbar auf dem Bild'];

function NewsletterChat({ exportOeffnen }: { exportOeffnen: Export }) {
  const auswahl = useSelectedBlockId();
  return (
    <ChatLeiste
      kontext={{ fenster: 'newsletter', auswahl }}
      hoehe="min(440px, 48vh)"
      vorschlaege={NEWSLETTER_VORSCHLAEGE}
      onExport={exportOeffnen}
    />
  );
}

function FensterChat({ exportOeffnen }: { exportOeffnen: Export }) {
  const id = pultStore((p) => p.gestaltungOffen);
  const auswahl = pultStore((p) => p.gestaltungAuswahl);
  const geaendert = pultStore((p) => p.gestaltungGeaendert);
  return (
    <ChatLeiste
      kontext={{ fenster: `flaeche:${id ?? ''}`, auswahl }}
      sperre={geaendert ? 'Erst „Zurück zum Newsletter“ – der Assistent arbeitet mit der gespeicherten Fläche.' : null}
      hoehe="min(360px, 45vh)"
      vorschlaege={FLAECHE_VORSCHLAEGE}
      onExport={exportOeffnen}
    />
  );
}

export default function App() {
  const inspectorDrawerOpen = useInspectorDrawerOpen();
  const arbeitet = useAgentArbeitet();
  const flaeche = pultStore((p) => p.gestaltungOffen);
  // null = zu; sonst offen mit Vorbelegung (null = Standard).
  const [exportDialog, setExportDialog] = useState<{ vorbelegt: ExportAuswahl | null } | null>(null);
  const exportOeffnen: Export = (vorbelegt) => setExportDialog({ vorbelegt });

  const marginRightTransition = useDrawerTransition('margin-right', inspectorDrawerOpen);
  const rechts = inspectorDrawerOpen ? INSPECTOR_DRAWER_WIDTH : 0;

  return (
    <>
      <AbschnittLeiste />
      <InspectorDrawer gesperrt={arbeitet !== null} chat={<NewsletterChat exportOeffnen={exportOeffnen} />} />

      <Stack
        sx={{
          marginLeft: `${ABSCHNITT_LEISTE_BREITE}px`,
          marginRight: `${rechts}px`,
          transition: marginRightTransition,
        }}
      >
        <TemplatePanel />
      </Stack>
      {/* Waehrend der Agent arbeitet: Abschnitte und Canvas gesperrt (die Pult-Leiste bleibt bedienbar). */}
      {arbeitet && (
        <SperrSchicht text={arbeitet} lage={{ position: 'fixed', top: PULT_LEISTE_HOEHE, left: 0, right: rechts, bottom: 0, zIndex: 1201 }} />
      )}
      {/* Vollbild ueber allem */}
      <GestaltungFenster
        onExportieren={() => exportOeffnen(flaeche ? { newsletter: false, flaechen: [flaeche] } : null)}
        chat={<FensterChat exportOeffnen={exportOeffnen} />}
      />
      <ExportDialog offen={exportDialog !== null} vorbelegt={exportDialog?.vorbelegt ?? null} onClose={() => setExportDialog(null)} />
    </>
  );
}
