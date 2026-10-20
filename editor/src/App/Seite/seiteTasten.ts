// Tastatur der Collage: Strg+Z/Y, Pfeile (1, Umschalt 10), Entf, Esc hebt die Auswahl auf.
// Dieselbe Fokusregel wie das Gestaltungsfenster (flaechenTaste); in Eingabefeldern gehoeren
// die Tasten immer dem Feld (auch im Textfeld auf der Flaeche).
import { useEffect, useRef } from 'react';

import { flaechenTaste, type TastenZiel } from '../Gestaltung/tasten';

import type { SeiteZustand } from './useSeite';

export type SeiteTasteEreignis = Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'preventDefault'>;
type Ziel = TastenZiel;
type Zustand = Pick<SeiteZustand, 'auswahl' | 'waehlen' | 'zurueck' | 'vor' | 'loeschen' | 'ebeneAendern' | 'aktuell'>;

const FELD = 'input, textarea, select, [contenteditable="true"]';

export function seiteTaste(ev: SeiteTasteEreignis, el: Ziel, z: Zustand): void {
  if (el !== null && el.matches(FELD)) return;
  if (!flaechenTaste(el)) return;
  if (ev.key === 'Escape') {
    if (z.auswahl !== null) z.waehlen(null);
    return;
  }
  const k = ev.key.toLowerCase();
  if ((ev.ctrlKey || ev.metaKey) && (k === 'z' || k === 'y')) {
    ev.preventDefault();
    if (k === 'y' || ev.shiftKey) z.vor();
    else z.zurueck();
    return;
  }
  const id = z.auswahl;
  if (id === null) return;
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    ev.preventDefault();
    z.loeschen(id);
    return;
  }
  if (!ev.key.startsWith('Arrow')) return;
  const e = z.aktuell().ebenen.find((x) => x.id === id);
  if (!e) return;
  ev.preventDefault();
  const d = ev.shiftKey ? 10 : 1;
  const dx = ev.key === 'ArrowLeft' ? -d : ev.key === 'ArrowRight' ? d : 0;
  const dy = ev.key === 'ArrowUp' ? -d : ev.key === 'ArrowDown' ? d : 0;
  z.ebeneAendern(id, { x: e.x + dx, y: e.y + dy }, 'gleiten');
}

export function useSeiteTasten(z: SeiteZustand): void {
  const zRef = useRef(z);
  zRef.current = z;
  useEffect(() => {
    const taste = (ev: KeyboardEvent) => {
      const el = ev.target instanceof HTMLElement && ev.target !== document.body ? ev.target : null;
      seiteTaste(ev, el, zRef.current);
    };
    window.addEventListener('keydown', taste);
    return () => window.removeEventListener('keydown', taste);
  }, []);
}
