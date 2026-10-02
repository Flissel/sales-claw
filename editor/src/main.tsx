import React from 'react';
import ReactDOM from 'react-dom/client';

import { CssBaseline, ThemeProvider } from '@mui/material';

import App from './App';
import { onDocumentChange, resetDocument } from './documents/editor/EditorContext';
import { TEditorConfiguration } from './documents/editor/core';
import { startLesen, zurAnzeige } from './pult';
import { alsUngespeichert, chatAbfragen, fensterWiederOeffnen, meldungLesen, pultStarten, standAbfragen } from './pultZustand';
import { pultThema } from './theme';
import './editor.css';

const wurzel = document.getElementById('root');
const dunkel = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;

function fehlerZeigen(el: HTMLElement, text: string) {
  const p = document.createElement('p');
  p.style.padding = '2rem';
  p.style.fontFamily = 'system-ui, sans-serif';
  p.textContent = text;
  el.replaceChildren(p);
}

// Vorlagenschriften (OFL, von sales-ui ausgeliefert, kein Google Fonts) fuer die
// Anzeige im Canvas; CSP erlaubt style-src/font-src 'self'.
const SCHRIFTEN_CSS = '/marketing/schrift/schriften.css';
if (!document.querySelector(`link[href="${SCHRIFTEN_CSS}"]`)) {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = SCHRIFTEN_CSS;
  document.head.appendChild(link);
}

if (wurzel) {
  try {
    const start = startLesen();
    pultStarten(start);
    standAbfragen();
    // Dokument aus dem Pult laden; Bilder "medien:<name>" zeigen wir ueber die
    // Medien-Adresse von sales-ui an (zurSpeicherung macht es beim Speichern rueckgaengig).
    resetDocument(zurAnzeige(start.dokument) as TEditorConfiguration);
    meldungLesen();
    // Nach dem Neuladen wegen einer Agenten-Fassung: offenes Gestaltungsfenster wieder oeffnen.
    fensterWiederOeffnen();
    onDocumentChange(alsUngespeichert);
    // Chat-Verlauf einmal laden; laeuft ein Auftrag, fragt chatAbfragen alle 2 s weiter.
    chatAbfragen();

    ReactDOM.createRoot(wurzel).render(
      <React.StrictMode>
        <ThemeProvider theme={pultThema(dunkel)}>
          <CssBaseline />
          <App />
        </ThemeProvider>
      </React.StrictMode>
    );
  } catch {
    fehlerZeigen(wurzel, 'Der Editor konnte den Entwurf nicht laden. Bitte die Seite neu laden oder zurück zum Entwurf gehen.');
  }
}

