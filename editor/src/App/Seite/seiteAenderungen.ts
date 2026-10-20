// Reine Aenderungen an einer Seite (ohne React), von useSeite genutzt. Jede laeuft durch klemmen.
import { MAX_EBENEN, type Seite, type SeitenEbene } from '../../seite';
import { klemmen } from '../../seiteGeometrie';

// Aenderung ohne id und art: eine Ebene kann so nie ihre Art wechseln.
export type EbenenTeil = SeitenEbene extends infer E ? (E extends unknown ? Omit<Partial<E>, 'id' | 'art'> : never) : never;

export function ebeneGeaendert(s: Seite, id: string, teil: EbenenTeil): Seite {
  if (!s.ebenen.some((e) => e.id === id)) return s;
  return {
    ...s,
    ebenen: s.ebenen.map((e) => (e.id === id ? klemmen({ ...e, ...teil, id: e.id, art: e.art } as SeitenEbene) : e)),
  };
}

export function ebeneDazu(s: Seite, e: SeitenEbene): Seite {
  if (s.ebenen.length >= MAX_EBENEN) return s;
  return { ...s, ebenen: [...s.ebenen, klemmen(e)] };
}

export function ebeneWeg(s: Seite, id: string): Seite {
  return { ...s, ebenen: s.ebenen.filter((e) => e.id !== id) };
}

/** Eine Stelle weiter nach oben (richtung +1, spaeter im Array) oder nach unten (-1). */
export function ebeneVerschoben(s: Seite, id: string, richtung: 1 | -1): Seite {
  const von = s.ebenen.findIndex((e) => e.id === id);
  const nach = von + richtung;
  if (von < 0 || nach < 0 || nach >= s.ebenen.length) return s;
  const liste = [...s.ebenen];
  [liste[von], liste[nach]] = [liste[nach], liste[von]];
  return { ...s, ebenen: liste };
}

