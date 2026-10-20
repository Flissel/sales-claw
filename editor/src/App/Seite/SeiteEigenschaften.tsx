// Rechte Spalte der Collage: Felder je Art mit den Bereichen aus Stufe 1 (claw/seite.py _ART),
// ohne Auswahl die Seite (Hoehe, Hintergrund, Vorschautext).
import React, { useState } from 'react';

import { FormatAlignCenterRounded, FormatAlignLeftRounded, FormatAlignRightRounded } from '@mui/icons-material';
import { Box, Button, MenuItem, Select, Switch, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';

import { HOEHE_MAX, HOEHE_MIN, MAX_TEXT, type BildEbeneS, type FormEbeneS, type KnopfEbeneS, type Rolle, type SeitenEbene, type TextEbeneS } from '../../seite';
import { Abschnitt, FarbFeld, Zahl, Zeile } from '../Gestaltung/Bedienelemente';
import { Medienauswahl } from '../Gestaltung/EbenenListe';
import { FARBE } from '../Gestaltung/gestaltungStil';

import { ebenenName } from './SeiteEbenen';
import type { EbenenTeil } from './seiteAenderungen';
import { seitenFarben } from './seiteStil';
import type { SeitenArt, SeiteZustand } from './useSeite';

export const ROLLEN_HINWEIS = 'Anrede ({vorname}) und Links gehen nur in der Rolle Fließtext ohne Drehung.';
const ROLLEN: Array<[Rolle, string]> = [['TEXT', 'Fließtext'], ['ANZEIGE', 'Anzeige (Markenschrift)'], ['HAND', 'Handschrift']];

type Aendern = (teil: EbenenTeil, art?: SeitenArt) => void;
type Farben = { laden: string[]; benutzt: string[] };

function Schalter({ label, an, onChange }: { label: string; an: boolean; onChange: (v: boolean) => void }) {
  return (
    <Zeile label={label}>
      <Switch size="small" checked={an} onChange={(ev) => onChange(ev.target.checked)} inputProps={{ 'aria-label': label }} />
    </Zeile>
  );
}

function Farbe({ label, wert, farben, onChange }: { label: string; wert: string; farben: Farben; onChange: (v: string, art: SeitenArt) => void }) {
  return (
    <Zeile label={label}>
      <FarbFeld label={label} wert={wert} laden={farben.laden} benutzt={farben.benutzt} onChange={(v, art) => onChange(v.toLowerCase(), art)} />
    </Zeile>
  );
}

function Lage({ e, aendern }: { e: SeitenEbene; aendern: Aendern }) {
  return (
    <Abschnitt titel="Lage">
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 1 }}>
        <Zahl label="X" wert={e.x} min={-600} max={1200} onChange={(v, art) => aendern({ x: v }, art)} />
        <Zahl label="Y" wert={e.y} min={-1000} max={7000} onChange={(v, art) => aendern({ y: v }, art)} />
        <Zahl label="B" wert={e.breite} min={1} max={1200} onChange={(v, art) => aendern({ breite: v }, art)} />
        <Zahl label="H" wert={e.hoehe} min={1} max={6000} onChange={(v, art) => aendern({ hoehe: v }, art)} />
      </Box>
      <Zeile label="Drehung">
        <Zahl label="↻" einheit="°" wert={e.drehung ?? 0} min={-180} max={180} onChange={(v, art) => aendern({ drehung: v }, art)} />
      </Zeile>
      <Zeile label="Deckkraft">
        <Zahl label="◐" einheit="%" wert={Math.round((e.deckkraft ?? 1) * 100)} min={0} max={100} onChange={(v, art) => aendern({ deckkraft: v / 100 }, art)} />
      </Zeile>
    </Abschnitt>
  );
}

function Mehrzeilig({ label, wert, max, zeilen, onChange }: { label: string; wert: string; max: number; zeilen: number; onChange: (v: string) => void }) {
  return (
    <TextField
      label={label}
      multiline={zeilen > 1}
      minRows={zeilen > 1 ? 3 : undefined}
      maxRows={zeilen > 1 ? 12 : undefined}
      value={wert}
      inputProps={{ maxLength: max }}
      onChange={(ev) => onChange(ev.target.value)}
      size="small"
      fullWidth
    />
  );
}

function BildFelder({ e, aendern, farben }: { e: BildEbeneS; aendern: Aendern; farben: Farben }) {
  const [anker, setAnker] = useState<HTMLElement | null>(null);
  return (
    <Abschnitt titel="Bild">
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography noWrap sx={{ flex: 1, fontSize: 13, color: FARBE.text }} title={ebenenName(e)}>{ebenenName(e)}</Typography>
        <Button size="small" color="inherit" onClick={(ev) => setAnker(ev.currentTarget)}>Ändern</Button>
      </Box>
      <Medienauswahl anker={anker} schliessen={() => setAnker(null)} waehlen={(name) => { setAnker(null); aendern({ quelle: `medien:${name}` }); }} />
      <Zeile label="Passung">
        <ToggleButtonGroup exclusive size="small" value={e.passung ?? 'fuellen'} onChange={(_, v: 'fuellen' | 'einpassen' | null) => v && aendern({ passung: v })}>
          <ToggleButton value="fuellen">Füllen</ToggleButton>
          <ToggleButton value="einpassen">Einpassen</ToggleButton>
        </ToggleButtonGroup>
      </Zeile>
      <Schalter label="Kreis" an={e.kreis ?? false} onChange={(v) => aendern({ kreis: v })} />
      {!e.kreis && (
        <Zeile label="Rundung"><Zahl label="◜" einheit="px" wert={e.rundung ?? 0} min={0} max={600} onChange={(v, art) => aendern({ rundung: v }, art)} /></Zeile>
      )}
      <Zeile label="Rahmen"><Zahl label="▢" einheit="px" wert={e.rahmen_breite ?? 0} min={0} max={20} onChange={(v, art) => aendern({ rahmen_breite: v }, art)} /></Zeile>
      {(e.rahmen_breite ?? 0) > 0 && <Farbe label="Rahmenfarbe" wert={e.rahmen_farbe ?? '#ffffff'} farben={farben} onChange={(v, art) => aendern({ rahmen_farbe: v }, art)} />}
      <Schalter label="Schatten" an={e.schatten ?? false} onChange={(v) => aendern({ schatten: v })} />
    </Abschnitt>
  );
}

function FormFelder({ e, aendern, farben }: { e: FormEbeneS; aendern: Aendern; farben: Farben }) {
  return (
    <Abschnitt titel="Form">
      <Zeile label="Form">
        <ToggleButtonGroup exclusive size="small" value={e.form} onChange={(_, v: 'rechteck' | 'kreis' | null) => v && aendern({ form: v })}>
          <ToggleButton value="rechteck">Rechteck</ToggleButton>
          <ToggleButton value="kreis">Kreis</ToggleButton>
        </ToggleButtonGroup>
      </Zeile>
      <Farbe label="Farbe" wert={e.farbe} farben={farben} onChange={(v, art) => aendern({ farbe: v }, art)} />
      {e.form === 'rechteck' && (
        <Zeile label="Rundung"><Zahl label="◜" einheit="px" wert={e.rundung ?? 0} min={0} max={600} onChange={(v, art) => aendern({ rundung: v }, art)} /></Zeile>
      )}
    </Abschnitt>
  );
}

function TextFelder({ e, aendern, farben }: { e: TextEbeneS; aendern: Aendern; farben: Farben }) {
  return (
    <Abschnitt titel="Text">
      <Mehrzeilig label="Text" wert={e.text} max={MAX_TEXT} zeilen={6} onChange={(v) => aendern({ text: v }, 'gleiten')} />
      <Typography sx={{ fontSize: 11, color: FARBE.gedaempft }}>**fett**, *kursiv*, [Linktext](https://…)</Typography>
      <Zeile label="Rolle">
        <Select size="small" fullWidth value={e.rolle} onChange={(ev) => aendern({ rolle: ev.target.value as Rolle })} inputProps={{ 'aria-label': 'Rolle' }}>
          {ROLLEN.map(([r, name]) => <MenuItem key={r} value={r}>{name}</MenuItem>)}
        </Select>
      </Zeile>
      <Typography sx={{ fontSize: 11, color: FARBE.gedaempft }}>{ROLLEN_HINWEIS}</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 1 }}>
        <Zahl label="Gr" einheit="px" wert={e.groesse} min={10} max={160} onChange={(v, art) => aendern({ groesse: v }, art)} />
        <Zahl label="Gw" wert={e.gewicht ?? 400} min={300} max={900} schritt={100} onChange={(v, art) => aendern({ gewicht: v }, art)} />
        <Zahl label="Zl" wert={e.zeilenabstand ?? 1.3} min={0.8} max={2.5} schritt={0.05} onChange={(v, art) => aendern({ zeilenabstand: v }, art)} />
        <Zahl label="Bs" einheit="em" wert={e.buchstabenabstand ?? 0} min={-0.1} max={0.5} schritt={0.01} onChange={(v, art) => aendern({ buchstabenabstand: v }, art)} />
      </Box>
      <Farbe label="Farbe" wert={e.farbe} farben={farben} onChange={(v, art) => aendern({ farbe: v }, art)} />
      <Zeile label="Ausrichtung">
        <ToggleButtonGroup exclusive size="small" value={e.ausrichtung ?? 'links'} onChange={(_, v: 'links' | 'mitte' | 'rechts' | null) => v && aendern({ ausrichtung: v })}>
          <ToggleButton value="links" aria-label="Links"><FormatAlignLeftRounded sx={{ fontSize: 16 }} /></ToggleButton>
          <ToggleButton value="mitte" aria-label="Mitte"><FormatAlignCenterRounded sx={{ fontSize: 16 }} /></ToggleButton>
          <ToggleButton value="rechts" aria-label="Rechts"><FormatAlignRightRounded sx={{ fontSize: 16 }} /></ToggleButton>
        </ToggleButtonGroup>
      </Zeile>
      <Schalter label="Versalien" an={e.grossbuchstaben ?? false} onChange={(v) => aendern({ grossbuchstaben: v })} />
      <Schalter label="Kursiv" an={e.kursiv ?? false} onChange={(v) => aendern({ kursiv: v })} />
      <Schalter label="Hintergrund" an={Boolean(e.hintergrund)} onChange={(v) => aendern({ hintergrund: v ? '#ffffff' : null })} />
      {e.hintergrund && <Farbe label="Hintergrundfarbe" wert={e.hintergrund} farben={farben} onChange={(v, art) => aendern({ hintergrund: v }, art)} />}
    </Abschnitt>
  );
}

function KnopfFelder({ e, aendern, farben }: { e: KnopfEbeneS; aendern: Aendern; farben: Farben }) {
  return (
    <Abschnitt titel="Knopf">
      <Mehrzeilig label="Text" wert={e.text} max={60} zeilen={1} onChange={(v) => aendern({ text: v }, 'gleiten')} />
      <Mehrzeilig label="Link (https://…)" wert={e.link} max={2000} zeilen={1} onChange={(v) => aendern({ link: v.trim() }, 'gleiten')} />
      <Farbe label="Farbe" wert={e.farbe} farben={farben} onChange={(v, art) => aendern({ farbe: v }, art)} />
      <Farbe label="Textfarbe" wert={e.textfarbe} farben={farben} onChange={(v, art) => aendern({ textfarbe: v }, art)} />
      <Zeile label="Rolle">
        <Select size="small" fullWidth value={e.rolle ?? 'TEXT'} onChange={(ev) => aendern({ rolle: ev.target.value as 'ANZEIGE' | 'TEXT' })} inputProps={{ 'aria-label': 'Rolle' }}>
          <MenuItem value="TEXT">Fließtext</MenuItem>
          <MenuItem value="ANZEIGE">Anzeige (Markenschrift)</MenuItem>
        </Select>
      </Zeile>
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 1 }}>
        <Zahl label="Gr" einheit="px" wert={e.groesse ?? 16} min={10} max={40} onChange={(v, art) => aendern({ groesse: v }, art)} />
        <Zahl label="Gw" wert={e.gewicht ?? 600} min={300} max={900} schritt={100} onChange={(v, art) => aendern({ gewicht: v }, art)} />
      </Box>
      <Zeile label="Rundung"><Zahl label="◜" einheit="px" wert={e.rundung ?? 6} min={0} max={60} onChange={(v, art) => aendern({ rundung: v }, art)} /></Zeile>
    </Abschnitt>
  );
}

// Die Spalte ist 320 breit: das Raster in jedem Abschnitt darf nicht mit langen Hinweisen mitwachsen.
function Spalte({ children }: { children: React.ReactNode }) {
  return <Box sx={{ '& section > div:last-child': { gridTemplateColumns: 'minmax(0, 1fr)' } }}>{children}</Box>;
}

type Props = { z: SeiteZustand; vorschautext: string; setVorschautext: (v: string) => void };

export default function SeiteEigenschaften({ z, vorschautext, setVorschautext }: Props) {
  const { seite: s } = z;
  const e = s.ebenen.find((x) => x.id === z.auswahl) ?? null;
  const farben: Farben = { laden: [], benutzt: seitenFarben(s) };
  if (!e) {
    return (
      <Spalte>
        <Abschnitt titel="Seite">
          <Zeile label="Höhe"><Zahl label="H" einheit="px" wert={s.hoehe} min={HOEHE_MIN} max={HOEHE_MAX} onChange={(v, art) => z.hoeheSetzen(v, art)} /></Zeile>
          <Farbe label="Hintergrund" wert={s.hintergrund.farbe} farben={farben} onChange={(v, art) => z.hintergrundSetzen(v, art)} />
        </Abschnitt>
        <Abschnitt titel="Postfach">
          <Mehrzeilig label="Vorschautext" wert={vorschautext} max={1000} zeilen={1} onChange={setVorschautext} />
          <Typography sx={{ fontSize: 12, color: FARBE.gedaempft }}>Eine Ebene anklicken, um sie zu bearbeiten.</Typography>
        </Abschnitt>
      </Spalte>
    );
  }
  const aendern: Aendern = (teil, art = 'sofort') => z.ebeneAendern(e.id, teil, art);
  return (
    <Spalte>
      {e.art === 'bild' && <BildFelder e={e} aendern={aendern} farben={farben} />}
      {e.art === 'form' && <FormFelder e={e} aendern={aendern} farben={farben} />}
      {e.art === 'text' && <TextFelder e={e} aendern={aendern} farben={farben} />}
      {e.art === 'knopf' && <KnopfFelder e={e} aendern={aendern} farben={farben} />}
      <Lage e={e} aendern={aendern} />
    </Spalte>
  );
}
