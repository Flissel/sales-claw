// Tastatur im Gestaltungsfenster: Strg+Z/Y, Pfeile (1, Shift 10), Entf, Esc hebt die Auswahl auf.
// Waehrend der Agent arbeitet oder der Newsletter zur Freigabe liegt (nurLesen), ist die Flaeche
// gesperrt - dann wirkt nur noch Esc (die Auswahl aufheben aendert nichts am Newsletter).
import { useEffect, useRef } from 'react';

import { schieben } from '../../gestaltung';
import { pultStore } from '../../pultZustand';

import { flaechenTaste, type TastenZiel } from './tasten';
import type { GestaltungZustand } from './useGestaltung';

export type FensterTasteEreignis = Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'preventDefault'>;

// Eine Taste auf die Flaeche anwenden (ohne DOM, damit testbar). el = Fokusziel (null = body).
export function fensterTaste(
  ev: FensterTasteEreignis,
  el: TastenZiel,
  zz: GestaltungZustand,
  versteckt: Set<string>,
  gesperrt: boolean
) {
  if (!flaechenTaste(el)) return;
  if (ev.key === 'Escape') {
    if (zz.auswahl !== null) zz.waehlen(null);
    return;
  }
  if (gesperrt) return;
  const k = ev.key.toLowerCase();
  if ((ev.ctrlKey || ev.metaKey) && (k === 'z' || k === 'y')) {
    ev.preventDefault();
    if (k === 'y' || ev.shiftKey) zz.vor();
    else zz.zurueck();
    return;
  }
  if (zz.auswahl === null) return;
  const id = zz.auswahl;
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    ev.preventDefault();
    zz.ebeneLoeschen(id);
  } else if (ev.key.startsWith('Arrow') && !versteckt.has(id)) {
    ev.preventDefault();
    const d = ev.shiftKey ? 10 : 1;
    const dx = ev.key === 'ArrowLeft' ? -d : ev.key === 'ArrowRight' ? d : 0;
    const dy = ev.key === 'ArrowUp' ? -d : ev.key === 'ArrowDown' ? d : 0;
    zz.ebeneAendern(id, (e) => schieben(e, dx, dy), 'gleiten');
  }
}

export function useFensterTasten(z: GestaltungZustand, versteckt: Set<string>) {
  const zRef = useRef(z);
  zRef.current = z;
  const verstecktRef = useRef(versteckt);
  verstecktRef.current = versteckt;
  useEffect(() => {
    const taste = (ev: KeyboardEvent) => {
      const { chat, nurLesen } = pultStore.getState();
      const el = ev.target instanceof HTMLElement && ev.target !== document.body ? ev.target : null;
      fensterTaste(ev, el, zRef.current, verstecktRef.current, Boolean(chat?.laeuft) || nurLesen);
    };
    window.addEventListener('keydown', taste);
    return () => window.removeEventListener('keydown', taste);
  }, []);
}
