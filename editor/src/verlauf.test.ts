import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  dokumentErsetzen,
  dokumentZeigen,
  setDocumentOhneVerlauf,
  getDocument,
  onDocumentChange,
  resetDocument,
  rueckgaengig,
  setDocument,
  VERLAUF_MAX,
  wiederholen,
  ZUSAMMENFASSEN_MS,
} from './documents/editor/EditorContext';
import { verlaufTaste } from './verlaufTasten';
import { TEditorConfiguration } from './documents/editor/core';

const AUSGANG = { root: { type: 'EmailLayout', data: { childrenIds: [] } } } as unknown as TEditorConfiguration;

function text(n: number) {
  return { t: { type: 'Text', data: { props: { text: `Stand ${n}` } } } } as unknown as TEditorConfiguration;
}
const stand = () => (getDocument() as unknown as { t?: { data: { props: { text: string } } } }).t?.data.props.text;

beforeEach(() => {
  vi.useFakeTimers();
  resetDocument(AUSGANG);
});
afterEach(() => vi.useRealTimers());

describe('Rückgängig/Wiederholen', () => {
  it('Konstanten', () => {
    expect(VERLAUF_MAX).toBe(50);
    expect(ZUSAMMENFASSEN_MS).toBe(500);
  });

  it('drei Änderungen im Abstand 600 ms sind drei Schritte bis zum Ausgang', () => {
    for (const n of [1, 2, 3]) {
      setDocument(text(n));
      vi.advanceTimersByTime(600);
    }
    expect(stand()).toBe('Stand 3');
    expect(rueckgaengig()).toBe(true);
    expect(stand()).toBe('Stand 2');
    expect(rueckgaengig()).toBe(true);
    expect(rueckgaengig()).toBe(true);
    expect(getDocument()).toEqual(AUSGANG);
    expect(rueckgaengig()).toBe(false);
  });

  it('zwei Änderungen im Abstand 100 ms sind ein Schritt (Tippen)', () => {
    setDocument(text(1));
    vi.advanceTimersByTime(100);
    setDocument(text(2));
    expect(rueckgaengig()).toBe(true);
    expect(getDocument()).toEqual(AUSGANG);
    expect(rueckgaengig()).toBe(false);
  });

  it('Wiederholen holt den Stand zurück', () => {
    setDocument(text(1));
    vi.advanceTimersByTime(600);
    setDocument(text(2));
    expect(rueckgaengig()).toBe(true);
    expect(stand()).toBe('Stand 1');
    expect(wiederholen()).toBe(true);
    expect(stand()).toBe('Stand 2');
    expect(wiederholen()).toBe(false);
  });

  it('nach Rückgängig und neuer Änderung ist Wiederholen leer', () => {
    setDocument(text(1));
    vi.advanceTimersByTime(600);
    setDocument(text(2));
    rueckgaengig();
    vi.advanceTimersByTime(600);
    setDocument(text(3));
    expect(wiederholen()).toBe(false);
    expect(stand()).toBe('Stand 3');
  });

  it('Rückgängig direkt nach einer Änderung fasst nicht mit dem Folgenden zusammen', () => {
    setDocument(text(1));
    vi.advanceTimersByTime(600);
    setDocument(text(2));
    rueckgaengig();
    // sofort weiter tippen: das ist ein neuer Schritt ab "Stand 1"
    setDocument(text(4));
    expect(rueckgaengig()).toBe(true);
    expect(stand()).toBe('Stand 1');
  });

  it('60 Schritte: nur die letzten 50 lassen sich zurücknehmen', () => {
    for (let n = 1; n <= 60; n++) {
      setDocument(text(n));
      vi.advanceTimersByTime(600);
    }
    let schritte = 0;
    while (rueckgaengig()) schritte++;
    expect(schritte).toBe(50);
    expect(stand()).toBe('Stand 10');
  });

  it('resetDocument (Laden, Agent-Fassung) leert beide Stapel – Strg+Z springt nicht davor', () => {
    setDocument(text(1));
    vi.advanceTimersByTime(600);
    setDocument(text(2));
    rueckgaengig();
    resetDocument(text(9));
    expect(rueckgaengig()).toBe(false);
    expect(wiederholen()).toBe(false);
    expect(stand()).toBe('Stand 9');
  });

  it('dokumentErsetzen (Block löschen/verschieben) ist ein Schritt', () => {
    setDocument(text(1));
    vi.advanceTimersByTime(600);
    dokumentErsetzen(AUSGANG);
    expect(getDocument()).toEqual(AUSGANG);
    expect(rueckgaengig()).toBe(true);
    expect(stand()).toBe('Stand 1');
  });

  it('setDocumentOhneVerlauf legt keinen Schritt ab und lässt Wiederholen stehen', () => {
    setDocument(text(1));
    vi.advanceTimersByTime(600);
    setDocument(text(2));
    rueckgaengig();
    setDocumentOhneVerlauf(text(5));
    expect(stand()).toBe('Stand 5');
    expect(rueckgaengig()).toBe(true);
    expect(getDocument()).toEqual(AUSGANG);
    expect(rueckgaengig()).toBe(false);
  });

  it('dokumentZeigen (Zwischenstand des Agenten) lässt beide Stapel stehen', () => {
    setDocument(text(1));
    const meins = getDocument();
    dokumentZeigen(text(7));
    expect(stand()).toBe('Stand 7');
    dokumentZeigen(meins);
    expect(rueckgaengig()).toBe(true);
    expect(getDocument()).toEqual(AUSGANG);
  });

  it('Rückgängig meldet eine Änderung (ungespeichert-Anzeige)', () => {
    setDocument(text(1));
    const cb = vi.fn();
    const ab = onDocumentChange(cb);
    try {
      rueckgaengig();
      expect(cb).toHaveBeenCalledTimes(1);
      wiederholen();
      expect(cb).toHaveBeenCalledTimes(2);
    } finally {
      ab();
    }
  });
});

describe('Tasten für Rückgängig/Wiederholen', () => {
  const ziel = (tag: string, editierbar = false) => ({ tagName: tag, isContentEditable: editierbar, closest: () => null });
  const t = (key: string, mod: { ctrl?: boolean; meta?: boolean; shift?: boolean } = {}, tag = 'DIV', editierbar = false) => ({
    key,
    ctrlKey: !!mod.ctrl,
    metaKey: !!mod.meta,
    shiftKey: !!mod.shift,
    altKey: false,
    target: ziel(tag, editierbar),
  });

  it('Strg/Cmd+Z, Strg/Cmd+Umschalt+Z, Strg+Y', () => {
    expect(verlaufTaste(t('z', { ctrl: true }), false)).toBe('rueckgaengig');
    expect(verlaufTaste(t('z', { meta: true }), false)).toBe('rueckgaengig');
    expect(verlaufTaste(t('Z', { ctrl: true, shift: true }), false)).toBe('wiederholen');
    expect(verlaufTaste(t('z', { meta: true, shift: true }), false)).toBe('wiederholen');
    expect(verlaufTaste(t('y', { ctrl: true }), false)).toBe('wiederholen');
    expect(verlaufTaste(t('z'), false)).toBeNull();
  });

  it('nicht in Textfeldern, nicht in contenteditable, nicht gesperrt', () => {
    expect(verlaufTaste(t('z', { ctrl: true }, 'INPUT'), false)).toBeNull();
    expect(verlaufTaste(t('z', { ctrl: true }, 'TEXTAREA'), false)).toBeNull();
    expect(verlaufTaste(t('z', { ctrl: true }, 'DIV', true), false)).toBeNull();
    const imEditierbaren = { ...t('z', { ctrl: true }), target: { tagName: 'SPAN', isContentEditable: false, closest: () => ({}) } };
    expect(verlaufTaste(imEditierbaren, false)).toBeNull();
    expect(verlaufTaste(t('z', { ctrl: true }), true)).toBeNull();
  });
});
