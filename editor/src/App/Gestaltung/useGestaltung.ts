// Zustand einer offenen Gestaltung: aktueller Stand, Auswahl und Rueckgaengig/Wiederholen.
// Ziehen und Scrollrad erzeugen viele Zwischenstaende; in den Verlauf kommt nur der
// Endstand (Ziehen: beim Loslassen; Scrollrad/Tippen: nach einer kurzen Ruhepause).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Ebene, Gestaltung, verlauf } from '../../gestaltung';

// 'sofort' = eigener Verlaufsschritt; 'gleiten' = mit den folgenden Aenderungen der
// naechsten 400 ms zusammengefasst; 'live' = erst festschreiben() schreibt ihn fest.
export type Art = 'sofort' | 'gleiten' | 'live';
const RUHE_MS = 400;

export function useGestaltung(anfang: Gestaltung) {
  const v = useMemo(() => verlauf(anfang), [anfang]);
  const [g, setG] = useState<Gestaltung>(anfang);
  const [auswahl, setAuswahl] = useState<string | null>(null);
  const jetzt = useRef(g);
  // Neuer Anfang von aussen (Live-Ansicht: der Agent hat die Flaeche geaendert): Stand und
  // Verlauf beginnen dort neu - schon beim Zeichnen, damit nichts kurz als geaendert gilt.
  const [basis, setBasis] = useState(anfang);
  if (basis !== anfang) {
    setBasis(anfang);
    setG(anfang);
    jetzt.current = anfang;
  }
  const takt = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Zeichnet neu, wenn ein Schritt festgeschrieben wird (Rueckgaengig/Wiederholen-Knoepfe).
  const [, setSchritte] = useState(0);

  const zeigen = useCallback((neu: Gestaltung) => {
    jetzt.current = neu;
    setG(neu);
  }, []);

  const festschreiben = useCallback(() => {
    if (takt.current) clearTimeout(takt.current);
    takt.current = null;
    // Nur echte Aenderungen werden ein Schritt (Blur/Loslassen ohne Bewegung erzeugt keinen leeren).
    if (v.jetzt() === jetzt.current) return;
    if (JSON.stringify(v.jetzt()) === JSON.stringify(jetzt.current)) {
      // inhaltlich gleich: zurueck auf den festgeschriebenen Stand (kein leerer Schritt)
      jetzt.current = v.jetzt();
      setG(v.jetzt());
      return;
    }
    v.setzen(jetzt.current);
    setSchritte((n) => n + 1);
  }, [v]);

  useEffect(() => () => {
    if (takt.current) clearTimeout(takt.current);
  }, []);

  const setzen = useCallback(
    (neu: Gestaltung, art: Art = 'sofort') => {
      zeigen(neu);
      if (art === 'sofort') festschreiben();
      else if (art === 'live') {
        // Ziehen laeuft: ein noch wartender Sammel-Takt darf keinen Zwischenstand festschreiben.
        if (takt.current) clearTimeout(takt.current);
        takt.current = null;
      } else {
        if (takt.current) clearTimeout(takt.current);
        takt.current = setTimeout(festschreiben, RUHE_MS);
      }
    },
    [zeigen, festschreiben]
  );

  const ebeneAendern = useCallback(
    (id: string, f: (e: Ebene) => Ebene, art: Art = 'sofort') => {
      const alt = jetzt.current;
      setzen({ ...alt, ebenen: alt.ebenen.map((e) => (e.id === id ? f(e) : e)) }, art);
    },
    [setzen]
  );

  const ebeneLoeschen = useCallback(
    (id: string) => {
      const alt = jetzt.current;
      setzen({ ...alt, ebenen: alt.ebenen.filter((e) => e.id !== id) });
      setAuswahl((a) => (a === id ? null : a));
    },
    [setzen]
  );

  const ebeneHinzufuegen = useCallback(
    (e: Ebene) => {
      const alt = jetzt.current;
      setzen({ ...alt, ebenen: [...alt.ebenen, e] });
      setAuswahl(e.id);
    },
    [setzen]
  );

  // von/nach = Indizes in ebenen (unterste zuerst).
  const verschieben = useCallback(
    (von: number, nach: number) => {
      const liste = [...jetzt.current.ebenen];
      if (von === nach || von < 0 || von >= liste.length) return;
      const [e] = liste.splice(von, 1);
      liste.splice(Math.max(0, Math.min(liste.length, nach)), 0, e);
      setzen({ ...jetzt.current, ebenen: liste });
    },
    [setzen]
  );

  const zurueck = useCallback(() => {
    festschreiben();
    if (v.zurueck()) zeigen(v.jetzt());
  }, [v, festschreiben, zeigen]);

  const vor = useCallback(() => {
    festschreiben();
    if (v.vor()) zeigen(v.jetzt());
  }, [v, festschreiben, zeigen]);

  // Nach Rueckgaengig kann die ausgewaehlte Ebene fehlen: dann gilt nichts als ausgewaehlt.
  const gewaehlt = auswahl !== null && g.ebenen.some((e) => e.id === auswahl) ? auswahl : null;

  return {
    g,
    aktuell: () => jetzt.current,
    auswahl: gewaehlt,
    waehlen: setAuswahl,
    setzen,
    festschreiben,
    ebeneAendern,
    ebeneLoeschen,
    ebeneHinzufuegen,
    verschieben,
    zurueck,
    vor,
    // Ein noch nicht festgeschriebener Stand zaehlt als rueckgaengig machbar (zurueck() schreibt ihn erst fest).
    kannZurueck: v.kannZurueck() || g !== v.jetzt(),
    kannVor: v.kannVor() && g === v.jetzt(),
  };
}

export type GestaltungZustand = ReturnType<typeof useGestaltung>;
