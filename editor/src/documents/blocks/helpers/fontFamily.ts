export const FONT_FAMILIES = [
  {
    key: 'MODERN_SANS',
    label: 'Modern (serifenlos)',
    value: '"Helvetica Neue", "Arial Nova", "Nimbus Sans", Arial, sans-serif',
  },
  {
    key: 'BOOK_SANS',
    label: 'Buch (serifenlos)',
    value: 'Optima, Candara, "Noto Sans", source-sans-pro, sans-serif',
  },
  {
    key: 'ORGANIC_SANS',
    label: 'Organisch',
    value: 'Seravek, "Gill Sans Nova", Ubuntu, Calibri, "DejaVu Sans", source-sans-pro, sans-serif',
  },
  {
    key: 'GEOMETRIC_SANS',
    label: 'Geometrisch',
    value: 'Avenir, "Avenir Next LT Pro", Montserrat, Corbel, "URW Gothic", source-sans-pro, sans-serif',
  },
  {
    key: 'HEAVY_SANS',
    label: 'Kräftig',
    value:
      'Bahnschrift, "DIN Alternate", "Franklin Gothic Medium", "Nimbus Sans Narrow", sans-serif-condensed, sans-serif',
  },
  {
    key: 'ROUNDED_SANS',
    label: 'Rund',
    value:
      'ui-rounded, "Hiragino Maru Gothic ProN", Quicksand, Comfortaa, Manjari, "Arial Rounded MT Bold", Calibri, source-sans-pro, sans-serif',
  },
  {
    key: 'MODERN_SERIF',
    label: 'Modern (Serifen)',
    value: 'Charter, "Bitstream Charter", "Sitka Text", Cambria, serif',
  },
  {
    key: 'BOOK_SERIF',
    label: 'Buch (Serifen)',
    value: '"Iowan Old Style", "Palatino Linotype", "URW Palladio L", P052, serif',
  },
  {
    key: 'MONOSPACE',
    label: 'Schreibmaschine',
    value: '"Nimbus Mono PS", "Courier New", "Cutive Mono", monospace',
  },
];

export const FONT_FAMILY_NAMES = [
  'MODERN_SANS',
  'BOOK_SANS',
  'ORGANIC_SANS',
  'GEOMETRIC_SANS',
  'HEAVY_SANS',
  'ROUNDED_SANS',
  'MODERN_SERIF',
  'BOOK_SERIF',
  'MONOSPACE',
] as const;
