/// <reference types="vitest" />
import { defineConfig } from 'vite';

// Gebaut wird nur das Skript und das Stylesheet fuer die Seite /kalender von
// sales-ui (ui_kalender.py liefert die Seite mit dem Daten-Element
// "kalender-start"). Einstieg ist main.ts, kein index.html.
export default defineConfig({
  base: '/static/kalender/',
  // Die Logik-Tests rechnen in der Ortszeit des Betriebs (Sommerzeit-Umstellung).
  test: { include: ['src/**/*.test.ts'], env: { TZ: 'Europe/Berlin' } },
  build: {
    outDir: '../sales-mcp/static/kalender',
    emptyOutDir: true,
    assetsInlineLimit: 100000000,
    cssCodeSplit: false,
    modulePreload: false,
    rollupOptions: {
      input: 'src/main.ts',
      output: {
        // Klassisches Skript (die Seite laedt es mit <script src defer>, nicht als Modul).
        format: 'iife',
        entryFileNames: 'kalender.js',
        assetFileNames: (a) => (a.name?.endsWith('.css') ? 'kalender.css' : '[name][extname]'),
        inlineDynamicImports: true,
      },
    },
  },
});
