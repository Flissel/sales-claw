import { create } from 'zustand';

import { TEditorConfiguration } from './core';

// Leeres Startdokument; das echte Dokument setzt main.tsx aus den Startdaten
// des Pults (resetDocument). Beispielvorlagen gibt es in diesem Fork nicht.
const LEER: TEditorConfiguration = {
  root: { type: 'EmailLayout', data: { childrenIds: [] } },
};

type TValue = {
  document: TEditorConfiguration;

  selectedBlockId: string | null;
  selectedSidebarTab: 'block-configuration' | 'styles';
  selectedScreenSize: 'desktop' | 'mobile';

  inspectorDrawerOpen: boolean;
};

const editorStateStore = create<TValue>(() => ({
  document: LEER,
  selectedBlockId: null,
  selectedSidebarTab: 'styles',
  selectedScreenSize: 'desktop',

  inspectorDrawerOpen: true,
}));

export function getDocument() {
  return editorStateStore.getState().document;
}

// Meldet jede Aenderung am Dokument (fuer "ungespeichert" in der Pult-Leiste).
export function onDocumentChange(cb: () => void) {
  return editorStateStore.subscribe((s, prev) => {
    if (s.document !== prev.document) cb();
  });
}

export function useDocument() {
  return editorStateStore((s) => s.document);
}

export function useSelectedBlockId() {
  return editorStateStore((s) => s.selectedBlockId);
}

export function useSelectedScreenSize() {
  return editorStateStore((s) => s.selectedScreenSize);
}

export function useSelectedSidebarTab() {
  return editorStateStore((s) => s.selectedSidebarTab);
}

export function useInspectorDrawerOpen() {
  return editorStateStore((s) => s.inspectorDrawerOpen);
}

export function setSelectedBlockId(selectedBlockId: TValue['selectedBlockId']) {
  const selectedSidebarTab = selectedBlockId === null ? 'styles' : 'block-configuration';
  const options: Partial<TValue> = {};
  if (selectedBlockId !== null) {
    options.inspectorDrawerOpen = true;
  }
  return editorStateStore.setState({
    selectedBlockId,
    selectedSidebarTab,
    ...options,
  });
}

export function setSidebarTab(selectedSidebarTab: TValue['selectedSidebarTab']) {
  return editorStateStore.setState({ selectedSidebarTab });
}

// Rueckgaengig/Wiederholen (Plan 2026-10-19 E11): hoechstens VERLAUF_MAX Schritte; Aenderungen
// innerhalb von ZUSAMMENFASSEN_MS nach dem letzten Ablegen zaehlen als ein Schritt (Tippen).
// resetDocument (Laden, Zwischenstand oder Fassung des Agenten) leert beide Stapel.
export const VERLAUF_MAX = 50;
export const ZUSAMMENFASSEN_MS = 500;

let zurueckStapel: TEditorConfiguration[] = [];
let vorStapel: TEditorConfiguration[] = [];
let zuletztAbgelegt = Number.NEGATIVE_INFINITY;

const verlaufStore = create(() => ({ kannZurueck: false, kannVor: false }));

function verlaufMelden() {
  verlaufStore.setState({ kannZurueck: zurueckStapel.length > 0, kannVor: vorStapel.length > 0 });
}

// Legt den Stand vor einer Aenderung ab und leert "Wiederholen".
function ablegen(vorher: TEditorConfiguration) {
  const jetzt = Date.now();
  if (zurueckStapel.length === 0 || jetzt - zuletztAbgelegt >= ZUSAMMENFASSEN_MS) {
    zurueckStapel.push(vorher);
    if (zurueckStapel.length > VERLAUF_MAX) zurueckStapel = zurueckStapel.slice(-VERLAUF_MAX);
    zuletztAbgelegt = jetzt;
  }
  vorStapel = [];
  verlaufMelden();
}

// Stand aus einem Stapel zeigen; eine Auswahl, die es dort nicht gibt, faellt weg.
function standZeigen(document: TEditorConfiguration) {
  const { selectedBlockId } = editorStateStore.getState();
  // Die naechste Aenderung beginnt immer einen neuen Schritt.
  zuletztAbgelegt = Number.NEGATIVE_INFINITY;
  if (selectedBlockId !== null && !(selectedBlockId in document)) {
    editorStateStore.setState({ document, selectedBlockId: null, selectedSidebarTab: 'styles' });
  } else {
    editorStateStore.setState({ document });
  }
  verlaufMelden();
}

export function rueckgaengig(): boolean {
  const vorher = zurueckStapel.pop();
  if (!vorher) return false;
  vorStapel.push(getDocument());
  standZeigen(vorher);
  return true;
}

export function wiederholen(): boolean {
  const nachher = vorStapel.pop();
  if (!nachher) return false;
  zurueckStapel.push(getDocument());
  standZeigen(nachher);
  return true;
}

export function useKannRueckgaengig(): boolean {
  return verlaufStore((s) => s.kannZurueck);
}

export function useKannWiederholen(): boolean {
  return verlaufStore((s) => s.kannVor);
}

export function resetDocument(document: TValue['document']) {
  zurueckStapel = [];
  vorStapel = [];
  zuletztAbgelegt = Number.NEGATIVE_INFINITY;
  verlaufMelden();
  return editorStateStore.setState({
    document,
    selectedSidebarTab: 'styles',
    selectedBlockId: null,
  });
}

// Wie resetDocument, aber als Schritt im Verlauf (Block duplizieren, loeschen, verschieben).
export function dokumentErsetzen(document: TValue['document']) {
  ablegen(getDocument());
  return editorStateStore.setState({
    document,
    selectedSidebarTab: 'styles',
    selectedBlockId: null,
  });
}

// Zeigt ein Dokument, ohne den Verlauf zu beruehren (Zwischenstand des Agenten und das Zurueckholen
// des echten Dokuments danach): ein Lauf ohne neue Fassung laesst Rueckgaengig/Wiederholen stehen.
export function dokumentZeigen(document: TValue['document']) {
  zuletztAbgelegt = Number.NEGATIVE_INFINITY;
  return editorStateStore.setState({
    document,
    selectedSidebarTab: 'styles',
    selectedBlockId: null,
  });
}

// Wie setDocument, aber ohne Rueckgaengig-Schritt (Uebernahme nach dem Speichern).
export function setDocumentOhneVerlauf(document: TValue['document']) {
  const originalDocument = editorStateStore.getState().document;
  return editorStateStore.setState({ document: { ...originalDocument, ...document } });
}

export function setDocument(document: TValue['document']) {
  const originalDocument = editorStateStore.getState().document;
  ablegen(originalDocument);
  return editorStateStore.setState({
    document: {
      ...originalDocument,
      ...document,
    },
  });
}

export function toggleInspectorDrawerOpen() {
  const inspectorDrawerOpen = !editorStateStore.getState().inspectorDrawerOpen;
  return editorStateStore.setState({ inspectorDrawerOpen });
}

export function setSelectedScreenSize(selectedScreenSize: TValue['selectedScreenSize']) {
  return editorStateStore.setState({ selectedScreenSize });
}
