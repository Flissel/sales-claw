// Aussehen des Gestaltungsfensters (Spec 2026-10-02 §3 "schoen von Anfang an"):
// dunkles, ruhiges Geruest - die Flaeche ist das Hellste am Schirm. Alle Farben,
// Masse und Uebergaenge kommen von hier, die Komponenten erfinden keine eigenen.
import { alpha, createTheme, Theme } from '@mui/material/styles';

// Palette aus den Global Constraints (woertlich).
export const FARBE = {
  geruest: '#0f0f11',
  panel: '#17171b',
  linie: '#2a2a31',
  text: '#ececf1',
  gedaempft: '#8d8d99',
  akzent: '#5b8cff',
  // abgeleitet, nicht neu: Flaechen fuer Eingaben/Hover und die Warnfarbe der Hinweise
  feld: '#1f1f25',
  hover: '#222229',
  warnung: '#e5b567',
  fehler: '#ff8b8b',
} as const;

export const UI_SCHRIFT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

// 8-px-Raster
export const RASTER = 8;
export const KOPF_HOEHE = 7 * RASTER; // 56
export const LINKS_BREITE = 30 * RASTER; // 240
export const RECHTS_BREITE = 40 * RASTER; // 320
export const ZEILE_HOEHE = 5 * RASTER; // 40 - Ebenenzeile, Kopfleisten-Knopf
export const BUEHNE_RAND = 6 * RASTER; // 48 - Luft um die Flaeche

export const UEBERGANG = '150ms ease-out';
export const uebergang = (...eigenschaften: string[]) => eigenschaften.map((e) => `${e} ${UEBERGANG}`).join(', ');

// Sichtbarer Fokus fuer alles, was man per Tastatur erreicht.
export const FOKUS = {
  outline: `2px solid ${FARBE.akzent}`,
  outlineOffset: 2,
} as const;

// Schachbrett hinter freigestellten Bildern (Transparenz sichtbar machen).
export const SCHACHBRETT = {
  backgroundColor: '#2b2b31',
  backgroundImage:
    'linear-gradient(45deg, #34343b 25%, transparent 25%), linear-gradient(-45deg, #34343b 25%, transparent 25%),' +
    'linear-gradient(45deg, transparent 75%, #34343b 75%), linear-gradient(-45deg, transparent 75%, #34343b 75%)',
  backgroundSize: '12px 12px',
  backgroundPosition: '0 0, 0 6px, 6px -6px, -6px 0',
} as const;

// Schatten der Flaeche: hebt sie vom Geruest ab, ohne Rahmen.
export const FLAECHE_SCHATTEN = '0 1px 2px rgba(0,0,0,0.5), 0 16px 48px rgba(0,0,0,0.55)';
// Ausserhalb der Flaeche wird abgedunkelt (Anschnitt bleibt greifbar, aber sichtbar "draussen").
export const AUSSEN_MASKE = alpha(FARBE.geruest, 0.78);

// Eigenes dunkles MUI-Thema nur fuer das Fenster: Eingaben, Menues, Tooltips passen zur Palette.
export function gestaltungThema(): Theme {
  const basis = createTheme({
    palette: {
      mode: 'dark',
      primary: { main: FARBE.akzent, contrastText: '#ffffff' },
      warning: { main: FARBE.warnung },
      error: { main: FARBE.fehler },
      background: { default: FARBE.geruest, paper: FARBE.panel },
      text: { primary: FARBE.text, secondary: FARBE.gedaempft },
      divider: FARBE.linie,
      action: { hover: FARBE.hover, selected: alpha(FARBE.akzent, 0.16) },
    },
    shape: { borderRadius: 6 },
    spacing: RASTER,
    typography: {
      fontFamily: UI_SCHRIFT,
      fontSize: 13,
      button: { textTransform: 'none', fontWeight: 600, letterSpacing: 0 },
    },
    transitions: { duration: { shortest: 150, shorter: 150, short: 150, standard: 150, complex: 150 } },
  });
  return createTheme(basis, {
    components: {
      MuiButtonBase: { defaultProps: { disableRipple: true } },
      MuiButton: {
        styleOverrides: {
          root: { height: 32, paddingInline: 12, transition: uebergang('background-color', 'color', 'border-color'), '&.Mui-focusVisible': FOKUS },
        },
      },
      MuiIconButton: {
        styleOverrides: {
          root: {
            borderRadius: 6,
            color: FARBE.gedaempft,
            transition: uebergang('background-color', 'color'),
            '&:hover': { color: FARBE.text, backgroundColor: FARBE.hover },
            '&.Mui-focusVisible': FOKUS,
          },
        },
      },
      MuiToggleButton: {
        styleOverrides: {
          root: {
            height: 32,
            border: 'none',
            color: FARBE.gedaempft,
            transition: uebergang('background-color', 'color'),
            '&.Mui-selected, &.Mui-selected:hover': { color: FARBE.text, backgroundColor: FARBE.linie },
            '&.Mui-focusVisible': FOKUS,
          },
        },
      },
      MuiToggleButtonGroup: {
        styleOverrides: { root: { backgroundColor: FARBE.feld, padding: 2, gap: 2, borderRadius: 8 }, grouped: { borderRadius: '6px !important' } },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            backgroundColor: FARBE.feld,
            fontSize: 13,
            transition: uebergang('border-color', 'box-shadow'),
            '& fieldset': { borderColor: 'transparent' },
            '&:hover fieldset': { borderColor: `${FARBE.linie} !important` },
            '&.Mui-focused fieldset': { borderColor: `${FARBE.akzent} !important`, borderWidth: '1px !important' },
          },
          input: { paddingTop: 7, paddingBottom: 7 },
        },
      },
      MuiTooltip: {
        defaultProps: { enterDelay: 300 },
        styleOverrides: {
          tooltip: { backgroundColor: '#2f2f37', color: FARBE.text, fontSize: 12, padding: '6px 8px', border: `1px solid ${FARBE.linie}` },
        },
      },
      MuiPopover: { styleOverrides: { paper: { backgroundImage: 'none', border: `1px solid ${FARBE.linie}`, boxShadow: FLAECHE_SCHATTEN } } },
      MuiMenu: { styleOverrides: { paper: { backgroundImage: 'none', border: `1px solid ${FARBE.linie}` } } },
      MuiMenuItem: { styleOverrides: { root: { fontSize: 13, minHeight: 36 } } },
    },
  });
}
