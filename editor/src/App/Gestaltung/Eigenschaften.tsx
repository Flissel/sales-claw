// Rechte Spalte: Eigenschaften der Auswahl (Bild oder Text) und der Alt-Text der Flaeche.
import React, { useEffect, useRef } from 'react';

import { FormatAlignCenterRounded, FormatAlignLeftRounded, FormatAlignRightRounded } from '@mui/icons-material';
import { Box, MenuItem, Select, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';

import { BildEbene, BREITE, Ebene, FORMATE, hoehe, TextEbene } from '../../gestaltung';
import { SCHNITTE, SCHRIFT_FAMILIE, SCHRIFT_IDS, SchriftId } from '../../schemata';

import { Abschnitt, FarbFeld, Zahl, Zeile } from './Bedienelemente';
import { ebenenName, istSchrift, schnittName } from './hilfen';
import { FARBE, RASTER } from './gestaltungStil';
import type { Art, GestaltungZustand } from './useGestaltung';

export const ALT_MAX = 200;
const TEXT_MAX = 200;
const ZEILEN_MAX = 6;

const FORMAT_NAME = { quer: 'Quer', quadrat: 'Quadrat', hoch: 'Hoch', banner: 'Banner' } as const;

// Anzeigename = erste Familie aus dem Register ("'DM Sans', Arial, …" -> DM Sans).
export function schriftName(id: SchriftId): string {
  return SCHRIFT_FAMILIE[id].split(',')[0].replace(/'/g, '').trim();
}

const laenge = (t: string) => [...t].length;

type Props = {
  z: GestaltungZustand;
  farben: { laden: string[]; benutzt: string[] };
  alt: string;
  setAlt: (a: string) => void;
  altFehlt: boolean;
  altRef: React.RefObject<HTMLTextAreaElement>;
  // Zaehler: jede Erhoehung fokussiert das Textfeld (Doppelklick auf einen Text).
  textFokus: number;
};

function Lage({ e, aendern }: { e: Ebene; aendern: (f: (x: Ebene) => Ebene, art: Art) => void }) {
  return (
    <>
      <Zeile label="Drehung">
        <Zahl label="↻" einheit="°" wert={e.drehung} min={-180} max={180} onChange={(v, art) => aendern((x) => ({ ...x, drehung: v }), art)} />
      </Zeile>
      <Zeile label="Position">
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1 }}>
          <Zahl label="X" wert={e.x} min={-600} max={1200} onChange={(v, art) => aendern((x) => ({ ...x, x: v }), art)} />
          <Zahl label="Y" wert={e.y} min={-750} max={1500} onChange={(v, art) => aendern((x) => ({ ...x, y: v }), art)} />
        </Box>
      </Zeile>
    </>
  );
}

function BildFelder({ e, aendern }: { e: BildEbene; aendern: (f: (x: Ebene) => Ebene, art: Art) => void }) {
  return (
    <Abschnitt titel="Bild">
      <Typography noWrap sx={{ fontSize: 13, color: FARBE.text, mb: 0.5 }} title={ebenenName(e)}>
        {ebenenName(e)}
      </Typography>
      <Zeile label="Breite">
        <Zahl label="B" wert={e.breite} min={8} max={3000} onChange={(v, art) => aendern((x) => (x.art === 'bild' ? { ...x, breite: v } : x), art)} />
      </Zeile>
      <Lage e={e} aendern={aendern} />
    </Abschnitt>
  );
}

function TextFelder({ e, aendern, farben, textRef }: { e: TextEbene; aendern: (f: (x: Ebene) => Ebene, art: Art) => void; farben: Props['farben']; textRef: React.RefObject<HTMLTextAreaElement> }) {
  const t = (f: (x: TextEbene) => TextEbene, art: Art = 'sofort') => aendern((x) => (x.art === 'text' ? f(x) : x), art);
  const schnitte = SCHNITTE[e.schrift as SchriftId] ?? [];
  const zeichen = laenge(e.text);
  return (
    <>
      <Abschnitt titel="Text" rechts={<Typography sx={{ fontSize: 11, color: zeichen >= TEXT_MAX ? FARBE.warnung : FARBE.gedaempft, fontVariantNumeric: 'tabular-nums' }}>{zeichen}/{TEXT_MAX}</Typography>}>
        <TextField
          inputRef={textRef}
          multiline
          minRows={2}
          maxRows={ZEILEN_MAX}
          fullWidth
          value={e.text}
          placeholder="Text eingeben"
          inputProps={{ 'aria-label': 'Text', spellCheck: true }}
          onChange={(ev) => {
            const v = ev.target.value;
            // Grenzen der Flaeche: hoechstens 200 Zeichen und 6 Zeilen (Umbruch nur mit Enter).
            if (laenge(v) <= TEXT_MAX && v.split('\n').length <= ZEILEN_MAX) t((x) => ({ ...x, text: v }), 'gleiten');
          }}
          sx={{ '& textarea': { lineHeight: 1.5 } }}
        />
        <Typography sx={{ fontSize: 11, color: FARBE.gedaempft }}>Neue Zeile mit Enter, höchstens {ZEILEN_MAX} Zeilen.</Typography>
      </Abschnitt>
      <Abschnitt titel="Schrift">
        <Select
          fullWidth
          size="small"
          value={e.schrift}
          inputProps={{ 'aria-label': 'Schrift' }}
          onChange={(ev) => {
            const s = ev.target.value;
            if (!istSchrift(s)) return;
            const da = SCHNITTE[s].some(([g, k]) => g === e.gewicht && k === e.kursiv);
            const [gewicht, kursiv] = da ? [e.gewicht, e.kursiv] : SCHNITTE[s][0];
            t((x) => ({ ...x, schrift: s, gewicht, kursiv }));
          }}
          renderValue={(v) => <span style={{ fontFamily: SCHRIFT_FAMILIE[v], fontSize: 15 }}>{istSchrift(v) ? schriftName(v) : v}</span>}
          MenuProps={{ slotProps: { paper: { sx: { maxHeight: 400 } } } }}
        >
          {SCHRIFT_IDS.map((id) => (
            <MenuItem key={id} value={id} sx={{ fontFamily: SCHRIFT_FAMILIE[id], fontWeight: SCHNITTE[id][0][0], fontSize: 17, minHeight: 40 }}>
              {schriftName(id)}
            </MenuItem>
          ))}
        </Select>
        <Zeile label="Schnitt">
          <Select
            fullWidth
            size="small"
            value={`${e.gewicht}-${e.kursiv ? 1 : 0}`}
            inputProps={{ 'aria-label': 'Schnitt' }}
            onChange={(ev) => {
              const [g, k] = String(ev.target.value).split('-');
              t((x) => ({ ...x, gewicht: Number(g), kursiv: k === '1' }));
            }}
          >
            {schnitte.map(([g, k]) => (
              <MenuItem key={`${g}-${k}`} value={`${g}-${k ? 1 : 0}`} sx={{ fontFamily: SCHRIFT_FAMILIE[e.schrift], fontWeight: g, fontStyle: k ? 'italic' : 'normal' }}>
                {schnittName(g, k)}
              </MenuItem>
            ))}
          </Select>
        </Zeile>
        <Zeile label="Größe">
          <Zahl label="Gr" wert={e.groesse} min={10} max={160} onChange={(v, art) => t((x) => ({ ...x, groesse: v }), art)} />
        </Zeile>
        <Zeile label="Zeilenabstand">
          <Zahl label="↕" wert={e.zeilenabstand} min={0.8} max={2} schritt={0.05} onChange={(v, art) => t((x) => ({ ...x, zeilenabstand: v }), art)} />
        </Zeile>
        <Zeile label="Farbe">
          <FarbFeld label="Textfarbe" wert={e.farbe} laden={farben.laden} benutzt={farben.benutzt} onChange={(v, art) => t((x) => ({ ...x, farbe: v }), art)} />
        </Zeile>
        <Zeile label="Ausrichtung">
          <ToggleButtonGroup
            exclusive
            fullWidth
            value={e.ausrichtung}
            aria-label="Ausrichtung"
            onChange={(_, v: TextEbene['ausrichtung'] | null) => {
              if (v) t((x) => ({ ...x, ausrichtung: v }));
            }}
          >
            <ToggleButton value="links" aria-label="Links">
              <FormatAlignLeftRounded sx={{ fontSize: 18 }} />
            </ToggleButton>
            <ToggleButton value="mitte" aria-label="Mitte">
              <FormatAlignCenterRounded sx={{ fontSize: 18 }} />
            </ToggleButton>
            <ToggleButton value="rechts" aria-label="Rechts">
              <FormatAlignRightRounded sx={{ fontSize: 18 }} />
            </ToggleButton>
          </ToggleButtonGroup>
        </Zeile>
      </Abschnitt>
      <Abschnitt titel="Lage">
        <Lage e={e} aendern={aendern} />
      </Abschnitt>
    </>
  );
}

const KUERZEL: Array<[string, string]> = [
  ['Ziehen', 'verschieben'],
  ['Scrollrad', 'Größe'],
  ['Shift + Scrollrad', 'drehen'],
  ['Pfeiltasten', '1 Einheit, mit Shift 10'],
  ['Alt beim Ziehen', 'ohne Einrasten'],
  ['Entf', 'Ebene löschen'],
  ['Strg + Z / Strg + Y', 'rückgängig / wiederholen'],
];

function Leer({ z }: { z: GestaltungZustand }) {
  const [a, b] = FORMATE[z.g.format];
  return (
    <Abschnitt titel="Fläche">
      <Typography sx={{ fontSize: 13, color: FARBE.text }}>
        {FORMAT_NAME[z.g.format]} {a}:{b} · {BREITE} × {hoehe(z.g.format)}
      </Typography>
      <Typography sx={{ fontSize: 12, color: FARBE.gedaempft, lineHeight: 1.6 }}>Eine Ebene anklicken, um sie einzustellen.</Typography>
      <Box component="dl" sx={{ m: 0, mt: 1, display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 2, rowGap: 1, fontSize: 12 }}>
        {KUERZEL.map(([k, w]) => (
          <React.Fragment key={k}>
            <Box component="dt" sx={{ color: FARBE.text }}>
              <Box component="kbd" sx={{ fontFamily: 'inherit', fontSize: 11, px: 0.75, py: 0.25, borderRadius: '4px', bgcolor: FARBE.feld, border: `1px solid ${FARBE.linie}` }}>
                {k}
              </Box>
            </Box>
            <Box component="dd" sx={{ m: 0, color: FARBE.gedaempft, alignSelf: 'center' }}>
              {w}
            </Box>
          </React.Fragment>
        ))}
      </Box>
    </Abschnitt>
  );
}

export default function Eigenschaften({ z, farben, alt, setAlt, altFehlt, altRef, textFokus }: Props) {
  const textRef = useRef<HTMLTextAreaElement>(null);
  const e = z.g.ebenen.find((x) => x.id === z.auswahl) ?? null;
  const aendern = (f: (x: Ebene) => Ebene, art: Art) => {
    if (e) z.ebeneAendern(e.id, f, art);
  };

  useEffect(() => {
    if (textFokus === 0) return;
    const el = textRef.current;
    if (el) {
      el.focus();
      el.select();
    }
  }, [textFokus]);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column' }}>
      {e === null && <Leer z={z} />}
      {e?.art === 'bild' && <BildFelder key={e.id} e={e} aendern={aendern} />}
      {e?.art === 'text' && <TextFelder key={e.id} e={e} aendern={aendern} farben={farben} textRef={textRef} />}
      <Abschnitt
        titel="Alternativtext der Fläche"
        rechts={<Typography sx={{ fontSize: 11, color: FARBE.gedaempft, fontVariantNumeric: 'tabular-nums' }}>{laenge(alt)}/{ALT_MAX}</Typography>}
      >
        <TextField
          inputRef={altRef}
          multiline
          minRows={2}
          fullWidth
          value={alt}
          error={altFehlt}
          placeholder="Was zeigt die Fläche? (Pflicht)"
          inputProps={{ 'aria-label': 'Alternativtext der Fläche', 'aria-required': true }}
          onChange={(ev) => {
            if (laenge(ev.target.value) <= ALT_MAX) setAlt(ev.target.value);
          }}
        />
        <Typography sx={{ fontSize: 11, color: altFehlt ? FARBE.fehler : FARBE.gedaempft, minHeight: RASTER * 2 }}>
          {altFehlt ? 'Bitte beschreiben – Pflicht für Screenreader und blockierte Bilder.' : 'Wird vorgelesen, wenn das Bild nicht angezeigt wird.'}
        </Typography>
      </Abschnitt>
    </Box>
  );
}
