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

export function resetDocument(document: TValue['document']) {
  return editorStateStore.setState({
    document,
    selectedSidebarTab: 'styles',
    selectedBlockId: null,
  });
}

export function setDocument(document: TValue['document']) {
  const originalDocument = editorStateStore.getState().document;
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
