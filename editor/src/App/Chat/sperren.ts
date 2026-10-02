// Sperre auch fuer die Tastatur: inert nimmt einen Bereich aus Tab-Reihenfolge und Eingabe.
// React 18 kennt das Attribut nicht - deshalb ueber die DOM-Eigenschaft per Ref.
import { useCallback, useEffect, useRef } from 'react';

export function inertSetzen(el: { inert: boolean } | null, aktiv: boolean) {
  if (el) el.inert = aktiv;
}

// Ref fuer einen Bereich, der waehrend `aktiv` inert ist.
export function useInert<T extends HTMLElement>(aktiv: boolean) {
  const el = useRef<T | null>(null);
  const aktivRef = useRef(aktiv);
  aktivRef.current = aktiv;
  useEffect(() => inertSetzen(el.current, aktiv), [aktiv]);
  return useCallback((knoten: T | null) => {
    el.current = knoten;
    inertSetzen(knoten, aktivRef.current);
  }, []);
}
