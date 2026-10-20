// Zustand einer offenen Collagen-Seite: Stand, Auswahl, Rueckgaengig/Wiederholen.
// Modi wie useGestaltung: 'sofort' = eigener Schritt; 'gleiten' = mit den Aenderungen der
// naechsten 400 ms zu einem Schritt zusammengefasst; 'live' = nichts im Verlauf, bis ein
// 'sofort'/'gleiten' oder zurueck/vor festschreibt.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { verlauf } from '../../gestaltung';
import type { Seite, SeitenEbene } from '../../seite';
import { hoeheZiehen } from '../../seiteGeometrie';
import {
  ebeneDazu, ebeneGeaendert, ebeneVerschoben, ebeneWeg, type EbenenTeil,
} from './seiteAenderungen';

export type SeitenArt = 'sofort' | 'gleiten' | 'live';
const RUHE_MS = 400;

export function useSeite(anfang: Seite) {
  const v = useMemo(() => verlauf(anfang), [anfang]);
  const [seite, setSeite] = useState<Seite>(anfang);
  const [auswahl, setAuswahl] = useState<string | null>(null);
  const [gespeicherterStand, setGespeichert] = useState<Seite>(anfang);
  const jetzt = useRef(seite);
  const [basis, setBasis] = useState(anfang);
  if (basis !== anfang) {
    setBasis(anfang);
    setSeite(anfang);
    setGespeichert(anfang);
    jetzt.current = anfang;
  }
  const takt = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [, setSchritte] = useState(0);

  const zeigen = useCallback((neu: Seite) => {
    jetzt.current = neu;
    setSeite(neu);
  }, []);

  const festschreiben = useCallback(() => {
    if (takt.current) clearTimeout(takt.current);
    takt.current = null;
    if (v.jetzt() === jetzt.current) return;
    if (JSON.stringify(v.jetzt()) === JSON.stringify(jetzt.current)) {
      jetzt.current = v.jetzt();
      setSeite(v.jetzt());
      return;
    }
    v.setzen(jetzt.current);
    setSchritte((n) => n + 1);
  }, [v]);

  useEffect(() => () => {
    if (takt.current) clearTimeout(takt.current);
  }, []);

  const setzen = useCallback(
    (neu: Seite, art: SeitenArt = 'sofort') => {
      zeigen(neu);
      if (art === 'sofort') festschreiben();
      else if (art === 'live') {
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
    (id: string, teil: EbenenTeil, modus: SeitenArt = 'sofort') =>
      setzen(ebeneGeaendert(jetzt.current, id, teil), modus),
    [setzen]
  );

  const hinzufuegen = useCallback(
    (e: SeitenEbene) => {
      const neu = ebeneDazu(jetzt.current, e);
      if (neu === jetzt.current) return;
      setzen(neu);
      setAuswahl(e.id);
    },
    [setzen]
  );

  const loeschen = useCallback(
    (id: string) => {
      setzen(ebeneWeg(jetzt.current, id));
      setAuswahl((a) => (a === id ? null : a));
    },
    [setzen]
  );

  const nachOben = useCallback((id: string) => setzen(ebeneVerschoben(jetzt.current, id, 1)), [setzen]);
  const nachUnten = useCallback((id: string) => setzen(ebeneVerschoben(jetzt.current, id, -1)), [setzen]);
  const hoeheSetzen = useCallback(
    (h: number, modus: SeitenArt = 'sofort') => setzen(hoeheZiehen(jetzt.current, h), modus),
    [setzen]
  );

  const hintergrundSetzen = useCallback(
    (farbe: string, modus: SeitenArt = 'sofort') => {
      const s = jetzt.current;
      setzen({ ...s, hintergrund: { ...s.hintergrund, farbe } }, modus);
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

  const gespeichert = useCallback(() => {
    festschreiben();
    setGespeichert(jetzt.current);
  }, [festschreiben]);

  const gewaehlt = auswahl !== null && seite.ebenen.some((e) => e.id === auswahl) ? auswahl : null;

  return {
    seite,
    aktuell: () => jetzt.current,
    auswahl: gewaehlt,
    waehlen: setAuswahl,
    festschreiben,
    ebeneAendern,
    hinzufuegen,
    loeschen,
    nachOben,
    nachUnten,
    hoeheSetzen,
    hintergrundSetzen,
    zurueck,
    vor,
    geaendert: seite !== gespeicherterStand,
    gespeichert,
    kannZurueck: v.kannZurueck() || seite !== v.jetzt(),
    kannVor: v.kannVor() && seite === v.jetzt(),
  };
}

export type SeiteZustand = ReturnType<typeof useSeite>;
