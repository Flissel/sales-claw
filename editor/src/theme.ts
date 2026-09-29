import { alpha, createTheme, Theme } from '@mui/material/styles';

import { DUNKEL, HELL, PultFarben, SCHRIFT } from './pultFarben';

const MONOSPACE_FONT_FAMILY =
  'ui-monospace, Menlo, Monaco, "Cascadia Mono", "Segoe UI Mono", "Roboto Mono", "Oxygen Mono", "Ubuntu Monospace", "Source Code Pro", "Fira Mono", "Droid Sans Mono", "Courier New", monospace';

export function pultThema(dunkel: boolean): Theme {
  const f: PultFarben = dunkel ? DUNKEL : HELL;
  const BASE_THEME = createTheme({
    palette: {
      mode: dunkel ? 'dark' : 'light',
      primary: { main: f.verweis },
      success: { main: f.gut },
      error: { main: f.fehler },
      warning: { main: f.achtung },
      info: { main: f.info },
      background: { default: f.grund, paper: f.flaeche },
      text: { primary: f.schrift, secondary: f.gedaempft },
      divider: f.linie,
      action: { selected: f.aktiv, hover: f.kopfzeile },
    },
    shape: { borderRadius: 8 },
    typography: { fontFamily: SCHRIFT, button: { textTransform: 'none', fontWeight: 600 } },
  });

  return createTheme(BASE_THEME, {
    components: {
      MuiCssBaseline: {
        styleOverrides: `
          address {
            font-style: normal;
          }
          fieldset {
            border: none;
            padding: 0;
          }
          pre {
            font-family: ${MONOSPACE_FONT_FAMILY}
            white-space: pre-wrap;
            font-size: 12px;
          }
        `,
      },
      MuiAlert: {
        styleOverrides: {
          root: {
            fontSize: BASE_THEME.typography.pxToRem(14),
          },
          action: {
            paddingTop: 0,
            marginRight: 0,
          },
          filledSuccess: {
            backgroundColor: f.gut,
          },
        },
      },
      MuiStepLabel: {
        styleOverrides: {
          label: {
            fontWeight: BASE_THEME.typography.fontWeightMedium,
          },
        },
      },
      MuiDialog: {
        defaultProps: {
          fullWidth: true,
        },
      },
      MuiDialogContent: {
        styleOverrides: {
          root: {
            paddingTop: BASE_THEME.spacing(1),
            paddingBottom: BASE_THEME.spacing(2),
          },
        },
      },
      MuiDialogTitle: {
        defaultProps: {
          variant: 'h4',
        },
        styleOverrides: {
          root: {
            paddingTop: BASE_THEME.spacing(3),
            paddingBottom: BASE_THEME.spacing(1),
          },
        },
      },
      MuiDialogActions: {
        styleOverrides: {
          root: {
            borderTop: '1px solid',
            borderTopColor: BASE_THEME.palette.divider,
            marginTop: BASE_THEME.spacing(2.5),
            padding: `${BASE_THEME.spacing(1.5)} ${BASE_THEME.spacing(3)}`,
          },
        },
      },
      MuiTableCell: {
        styleOverrides: {
          root: {
            ...BASE_THEME.typography.body2,
            borderColor: f.linie,
          },
          head: {
            ...BASE_THEME.typography.overline,
            fontWeight: BASE_THEME.typography.fontWeightMedium,
            letterSpacing: '0.075em',
            color: BASE_THEME.palette.text.secondary,
          },
        },
      },
      MuiTableRow: {
        styleOverrides: {
          root: {
            '&:last-child td': {
              borderBottom: 0,
            },
          },
        },
      },
      MuiAvatar: {
        styleOverrides: {
          root: {
            textTransform: 'uppercase',
            fontSize: BASE_THEME.typography.pxToRem(14),
          },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            '&.MuiChip-filledError, &.MuiChip-filledSuccess': {
              fill: BASE_THEME.palette.primary.contrastText,
            },
          },
          sizeSmall: {
            borderRadius: BASE_THEME.spacing(0.5),
            fontSize: 12,
          },
          iconSmall: {
            fontSize: 14,
            marginLeft: BASE_THEME.spacing(1),
          },
          colorSecondary: {
            borderColor: f.linie_stark,
            color: BASE_THEME.palette.text.secondary,
          },
          label: {
            fontWeight: BASE_THEME.typography.fontWeightMedium,
          },
        },
      },
      MuiDrawer: {
        defaultProps: {
          PaperProps: {
            elevation: 0,
          },
        },
        styleOverrides: { paper: { backgroundColor: f.flaeche, borderColor: f.linie } },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            fontSize: BASE_THEME.typography.pxToRem(12),
            backgroundColor: alpha(BASE_THEME.palette.text.primary, 0.9),
          },
        },
      },
      MuiSlider: {
        styleOverrides: {
          root: {
            height: 1,
          },
          track: {
            height: 1,
            border: 'none',
          },
          rail: {
            height: 1,
            backgroundColor: f.linie_stark,
          },
          mark: {
            backgroundColor: f.linie_stark,
          },
          markActive: {
            height: 0,
          },
          thumb: {
            height: 16,
            width: 16,
            cursor: 'col-resize',
            '&:hover, &.Mui-active, &.Mui-focusVisible': {
              boxShadow: `0 0 0 4px ${alpha(f.verweis, 0.2)}`,
            },
            '&:before': {
              display: 'none',
            },
          },
        },
      },
      MuiPaper: {
        defaultProps: {
          elevation: 2,
          square: true,
        },
      },
      MuiButtonBase: {
        defaultProps: {
          disableTouchRipple: true,
          focusRipple: true,
        },
        styleOverrides: {
          root: {
            '&.MuiButton-containedSecondary.Mui-disabled': {
              backgroundColor: f.kopfzeile,
            },
          },
        },
      },
      MuiButtonGroup: {
        defaultProps: {
          disableElevation: true,
        },
      },
      MuiIconButton: {
        styleOverrides: {
          edgeStart: {
            marginLeft: BASE_THEME.spacing(-1),
          },
          colorSecondary: {
            color: f.linie_stark,
          },
        },
      },
      MuiButton: {
        defaultProps: {
          disableElevation: true,
        },
        styleOverrides: {
          textPrimary: {
            color: BASE_THEME.palette.text.primary,
          },
          textSecondary: {
            color: BASE_THEME.palette.text.secondary,
          },
          outlinedPrimary: {
            borderColor: f.linie,
            color: BASE_THEME.palette.text.primary,
            '&:hover, &:active, &:focus': {
              borderColor: f.linie_stark,
              color: BASE_THEME.palette.text.primary,
            },
          },
          containedSecondary: {
            backgroundColor: f.flaeche,
            border: `1px solid ${f.linie}`,
            color: BASE_THEME.palette.text.primary,
            '&:hover, &:active, &:focus': {
              backgroundColor: f.flaeche,
              borderColor: f.linie_stark,
              color: BASE_THEME.palette.text.primary,
            },
          },
        },
      },
      MuiToggleButton: {
        styleOverrides: {
          root: {
            paddingLeft: BASE_THEME.spacing(1.5),
            paddingRight: BASE_THEME.spacing(1.5),
          },
        },
      },
      MuiInputBase: {
        styleOverrides: {
          root: {
            '&:not(.Mui-disabled, .Mui-error):before': {
              borderBottom: `1px solid ${f.linie_stark}`,
            },
            '&:hover:not(.Mui-disabled, .Mui-error):before': {
              borderBottom: `1px solid ${f.linie_stark} !important`,
            },
            '&:after': {
              borderBottom: `1px solid ${BASE_THEME.palette.text.primary} !important`,
            },
            '&.MuiOutlinedInput-root:not(.Mui-error)': {
              '& fieldset': {
                borderColor: f.linie,
                transition: 'border-color 0.2s',
              },
            },
            '&.MuiOutlinedInput-root:not(.Mui-disabled, .Mui-error)': {
              '&:hover fieldset': {
                borderColor: f.linie_stark,
              },
              '&.Mui-focused fieldset': {
                borderColor: BASE_THEME.palette.text.secondary,
                borderWidth: 1,
              },
            },
          },
          input: {
            fontSize: BASE_THEME.typography.pxToRem(14),
            '&.Mui-disabled': {
              WebkitTextFillColor: 'inherit',
              color: BASE_THEME.palette.text.secondary,
            },
          },
          inputSizeSmall: {},
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          notchedOutline: {
            '& legend': {
              fontSize: '0.85em',
              maxWidth: '100%',
            },
          },
        },
      },
      MuiInputAdornment: {
        styleOverrides: {
          root: {
            '& .MuiTypography-root': {
              fontSize: BASE_THEME.typography.pxToRem(14),
              color: BASE_THEME.palette.text.secondary,
            },
          },
        },
      },
      MuiInputLabel: {
        defaultProps: {
          shrink: true,
        },
        styleOverrides: {
          shrink: {
            transform: 'scale(0.85)',
            fontWeight: BASE_THEME.typography.fontWeightMedium,
            '&.Mui-focused': {
              color: BASE_THEME.palette.text.primary,
            },
            '&.MuiInputLabel-standard': {
              transform: 'translate(0, -4px) scale(0.85)',
              color: f.gedaempft,
            },
            '&.MuiInputLabel-outlined': {
              transform: 'translate(15px, -8px) scale(0.85)',
            },
          },
        },
      },
      MuiTabs: {
        defaultProps: {
          variant: 'scrollable',
        },
        styleOverrides: {
          indicator: {
            height: 1,
            backgroundColor: BASE_THEME.palette.text.primary,
          },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            minWidth: BASE_THEME.spacing(2),
            paddingLeft: BASE_THEME.spacing(1.5),
            paddingRight: BASE_THEME.spacing(1.5),
            fontSize: BASE_THEME.typography.pxToRem(14),
            fontFamily: BASE_THEME.typography.fontFamily,
            lineHeight: 1.5,
            fontWeight: BASE_THEME.typography.fontWeightMedium,
            transition: 'color 0.2s',
            '&.Mui-selected': {
              color: BASE_THEME.palette.text.primary,
            },
            '&:hover': {
              color: BASE_THEME.palette.text.primary,
            },
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 0,
          },
        },
      },
      MuiCardHeader: {
        styleOverrides: {
          title: {
            fontSize: BASE_THEME.typography.pxToRem(18),
            fontWeight: BASE_THEME.typography.fontWeightMedium,
          },
        },
      },
    },
    typography: {
      fontFamily: BASE_THEME.typography.fontFamily,
      h1: {
        fontFamily: BASE_THEME.typography.fontFamily,
        fontSize: BASE_THEME.typography.pxToRem(40),
        lineHeight: 1.2,
        letterSpacing: '-0.02em',
        fontWeight: BASE_THEME.typography.fontWeightMedium,
      },
      h2: {
        fontFamily: BASE_THEME.typography.fontFamily,
        fontSize: BASE_THEME.typography.pxToRem(32),
        lineHeight: 1.2,
        letterSpacing: '-0.02em',
        fontWeight: BASE_THEME.typography.fontWeightMedium,
      },
      h3: {
        fontFamily: BASE_THEME.typography.fontFamily,
        fontSize: BASE_THEME.typography.pxToRem(24),
        lineHeight: 1.5,
        letterSpacing: '-0.01em',
        fontWeight: BASE_THEME.typography.fontWeightMedium,
      },
      h4: {
        fontFamily: BASE_THEME.typography.fontFamily,
        fontSize: BASE_THEME.typography.pxToRem(20),
        lineHeight: 1.5,
        letterSpacing: '-0.01em',
        fontWeight: BASE_THEME.typography.fontWeightMedium,
      },
      h5: {
        fontFamily: BASE_THEME.typography.fontFamily,
        fontSize: BASE_THEME.typography.pxToRem(18),
        lineHeight: 1.5,
        letterSpacing: '-0.01em',
        fontWeight: BASE_THEME.typography.fontWeightMedium,
      },
      h6: {
        fontFamily: BASE_THEME.typography.fontFamily,
        fontSize: BASE_THEME.typography.pxToRem(16),
        lineHeight: 1.5,
        letterSpacing: '-0.005em',
        fontWeight: BASE_THEME.typography.fontWeightMedium,
      },
      body1: {
        fontSize: BASE_THEME.typography.pxToRem(14),
      },
      body2: {
        fontSize: BASE_THEME.typography.pxToRem(12),
      },
      overline: {
        fontWeight: BASE_THEME.typography.fontWeightMedium,
        letterSpacing: '0.05em',
      },
      button: {
        textTransform: 'none',
        fontWeight: BASE_THEME.typography.fontWeightMedium,
        lineHeight: 1.5,
      },
      caption: {
        letterSpacing: 0,
        lineHeight: 1.5,
      },
    },
    shadows: [
      'none',
      '0px 4px 15px rgba(28, 27, 24, 0.04), 0px 0px 2px rgba(28, 27, 24, 0.04), 0px 0px 1px rgba(28, 27, 24, 0.04)',
      '0px 10px 20px rgba(28, 27, 24, 0.04), 0px 2px 6px rgba(28, 27, 24, 0.04), 0px 0px 1px rgba(28, 27, 24, 0.04)',
      '0px 16px 24px rgba(28, 27, 24, 0.05), 0px 2px 6px rgba(28, 27, 24, 0.05), 0px 0px 1px rgba(28, 27, 24, 0.05)',
      '0px 24px 32px rgba(28, 27, 24, 0.06), 0px 16px 24px rgba(28, 27, 24, 0.06), 0px 4px 8px rgba(28, 27, 24, 0.06)',
      ...Array(20).fill('none'),
    ],
  });
}

export default pultThema(false);
