import { create } from 'zustand';

import type { Auftrag } from './bildfeld';
import { medienListe, standLaden, Start } from './pult';

// Zustand der Pult-Leiste: Startdaten, Betreff/Vorschautext, gemerkte Fassung
// und ob seit dem letzten Speichern etwas geaendert wurde.
type TPult = {
  start: Start | null;
  betreff: string;
  vorschautext: string;
  basis: number;
  ungespeichert: boolean;
  medien: string[] | null;
  stand: { fassung: number; auftraege: Auftrag[] } | null;
};

export const pultStore = create<TPult>(() => ({
  start: null,
  betreff: '',
  vorschautext: '',
  basis: 0,
  ungespeichert: false,
  medien: null,
  stand: null,
}));

export function pultStarten(start: Start) {
  pultStore.setState({
    start,
    betreff: start.betreff ?? '',
    vorschautext: start.vorschautext ?? '',
    basis: start.basis_fassung,
    ungespeichert: false,
  });
}

export function alsUngespeichert() {
  if (!pultStore.getState().ungespeichert) pultStore.setState({ ungespeichert: true });
}

let medienLaeuft: Promise<void> | null = null;
export function medienLaden(neu = false) {
  const { start } = pultStore.getState();
  if (!start) return;
  if (medienLaeuft && !neu) return;
  medienLaeuft = medienListe(start).then((medien) => pultStore.setState({ medien }));
}

let standTakt: ReturnType<typeof setInterval> | null = null;
export function standAbfragen() {
  const holen = async () => {
    const { start } = pultStore.getState();
    if (!start) return;
    const s = await standLaden(start);
    if (s) pultStore.setState({ stand: s });
  };
  void holen();
  if (!standTakt) standTakt = setInterval(holen, 15000);
}
