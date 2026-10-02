// Tastatur im Gestaltungsfenster: Strg+Z/Y, Pfeile (1, Shift 10), Entf, Esc hebt die Auswahl auf.
// Waehrend der Agent arbeitet, ist die Flaeche gesperrt - dann wirkt keine Taste.
import { useEffect, useRef } from 'react';

import { schieben } from '../../gestaltung';
import { pultStore } from '../../pultZustand';

import { flaechenTaste } from './tasten';
import type { GestaltungZustand } from './useGestaltung';

export function useFensterTasten(z: GestaltungZustand, versteckt: Set<string>) {
  const zRef = useRef(z);
  zRef.current = z;
  const verstecktRef = useRef(versteckt);
  verstecktRef.current = versteckt;
  useEffect(() => {
    const taste = (ev: KeyboardEvent) => {
      if (pultStore.getState().chat?.laeuft) return;
      const zz = zRef.current;
      const el = ev.target instanceof HTMLElement && ev.target !== document.body ? ev.target : null;
      if (!flaechenTaste(el)) return;
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
      } else if (ev.key === 'Escape') {
        zz.waehlen(null);
      } else if (ev.key.startsWith('Arrow') && !verstecktRef.current.has(id)) {
        ev.preventDefault();
        const d = ev.shiftKey ? 10 : 1;
        const dx = ev.key === 'ArrowLeft' ? -d : ev.key === 'ArrowRight' ? d : 0;
        const dy = ev.key === 'ArrowUp' ? -d : ev.key === 'ArrowDown' ? d : 0;
        zz.ebeneAendern(id, (e) => schieben(e, dx, dy), 'gleiten');
      }
    };
    window.addEventListener('keydown', taste);
    return () => window.removeEventListener('keydown', taste);
  }, []);
}
