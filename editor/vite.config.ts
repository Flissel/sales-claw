import { defineConfig } from 'vite';

import react from '@vitejs/plugin-react-swc';

// Gebaut wird nur das Skript und das Stylesheet fuer die Editor-Seite von
// sales-ui (Task 6 liefert die Seite mit dem Daten-Element "editor-start").
// Einstieg ist main.tsx, nicht index.html, damit kein HTML ausgeliefert wird.
export default defineConfig({
  plugins: [react()],
  base: '/static/editor/',
  build: {
    outDir: '../sales-mcp/static/editor',
    emptyOutDir: true,
    assetsInlineLimit: 100000000,
    cssCodeSplit: false,
    modulePreload: false,
    rollupOptions: {
      input: 'src/main.tsx',
      output: {
        // Klassisches Skript (die Seite laedt es mit <script src defer>, nicht als Modul).
        format: 'iife',
        entryFileNames: 'editor.js',
        assetFileNames: (a) => (a.name?.endsWith('.css') ? 'editor.css' : '[name][extname]'),
        inlineDynamicImports: true,
      },
    },
  },
});
