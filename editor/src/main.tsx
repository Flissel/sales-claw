import React from 'react';
import ReactDOM from 'react-dom/client';

import { CssBaseline, ThemeProvider } from '@mui/material';

import App from './App';
import { onDocumentChange, resetDocument } from './documents/editor/EditorContext';
import { TEditorConfiguration } from './documents/editor/core';
import { startLesen, zurAnzeige } from './pult';
import { alsUngespeichert, pultStarten } from './pultZustand';
import theme from './theme';
import './editor.css';

const wurzel = document.getElementById('root');

function fehlerZeigen(el: HTMLElement, text: string) {
  const p = document.createElement('p');
  p.style.padding = '2rem';
  p.style.fontFamily = 'system-ui, sans-serif';
  p.textContent = text;
  el.replaceChildren(p);
}

if (wurzel) {
  try {
    const start = startLesen();
    pultStarten(start);
    // Dokument aus dem Pult laden; Bilder "medien:<name>" zeigen wir ueber die
    // Medien-Adresse von sales-ui an (zurSpeicherung macht es beim Speichern rueckgaengig).
    resetDocument(zurAnzeige(start.dokument) as TEditorConfiguration);
    onDocumentChange(alsUngespeichert);

    ReactDOM.createRoot(wurzel).render(
      <React.StrictMode>
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <App />
        </ThemeProvider>
      </React.StrictMode>
    );
  } catch {
    fehlerZeigen(wurzel, 'Der Editor konnte den Entwurf nicht laden. Bitte die Seite neu laden oder zurück zum Entwurf gehen.');
  }
}
