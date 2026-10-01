import React, { useEffect, useState } from 'react';
import { ZodError } from 'zod';

import {
  VerticalAlignBottomOutlined,
  VerticalAlignCenterOutlined,
  VerticalAlignTopOutlined,
} from '@mui/icons-material';
import {
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';
import { ImageProps, ImagePropsSchema } from '@usewaypoint/block-image';

import {
  erzeugenSperre,
  formatText,
  istLeer,
  istPlatz,
  knopfText,
  staerkeWert,
  standFuer,
  STUFE_FREI,
  STUFE_NAH,
  STUFE_NEU,
} from '../../../../bildfeld';
import { bildBeauftragen, ANZEIGE, medienName } from '../../../../pult';
import { medienLaden, pultStore, standAbfragen } from '../../../../pultZustand';
import { useSelectedBlockId } from '../../../../documents/editor/EditorContext';

import BaseSidebarPanel from './helpers/BaseSidebarPanel';
import RadioGroupInput from './helpers/inputs/RadioGroupInput';
import TextDimensionInput from './helpers/inputs/TextDimensionInput';
import TextInput from './helpers/inputs/TextInput';
import MultiStylePropertyPanel from './helpers/style-inputs/MultiStylePropertyPanel';

type ImageSidebarPanelProps = {
  data: ImageProps;
  setData: (v: ImageProps) => void;
};
export default function ImageSidebarPanel({ data, setData }: ImageSidebarPanelProps) {
  const [, setErrors] = useState<ZodError | null>(null);
  const medien = pultStore((p) => p.medien);
  const stand = pultStore((p) => p.stand);
  const start = pultStore((p) => p.start);
  const ungespeichert = pultStore((p) => p.ungespeichert);
  const selectedBlockId = useSelectedBlockId();
  const [hinweis, setHinweis] = useState('');
  const [stufe, setStufe] = useState<number>(STUFE_NAH);
  const [neu, setNeu] = useState(false);
  const [laeuft, setLaeuft] = useState(false);
  const [rueckmeldung, setRueckmeldung] = useState<{ art: 'ok' | 'fehler'; text: string } | null>(null);
  useEffect(() => {
    medienLaden();
    // Panel weg (anderer Block gewaehlt): der Hinweis ist verworfen und blockiert das Neuladen nicht mehr.
    return () => pultStore.setState({ hinweisOffen: false });
  }, []);

  // Das freie URL-Feld gibt es hier nicht: Bilder kommen nur aus den Medien.
  const aktuell = data.props?.url ?? '';
  // medienName faengt ein kaputtes %-Zeichen ab (sonst wuerfe das Panel beim Zeichnen).
  const name = medienName(aktuell);
  const kaputt = aktuell.startsWith(ANZEIGE) && name === null;
  const gewaehlt = name ?? '';
  const optionen = medien ?? [];
  const fehltInListe = gewaehlt !== '' && !optionen.includes(gewaehlt);
  // Platzhalter-Bilder sind keine Auswahl, nur Markierung fuer leere Plaetze.
  const kacheln = optionen.filter((n) => !n.startsWith('platzhalter-'));
  const platz = istPlatz(data.props);
  const leer = istLeer(aktuell);
  const sperre = erzeugenSperre(ungespeichert, data.props ?? undefined);
  const s = selectedBlockId ? standFuer(selectedBlockId, stand?.auftraege ?? []) : { text: '', art: null };

  const erzeugen = async () => {
    if (!start || !selectedBlockId || sperre) return;
    setLaeuft(true);
    setRueckmeldung(null);
    const e = await bildBeauftragen(
      start,
      selectedBlockId,
      hinweis.trim(),
      staerkeWert(neu || leer ? STUFE_NEU : stufe),
      neu || leer,
    );
    setLaeuft(false);
    if (e.ok) {
      setHinweis('');
      pultStore.setState({ hinweisOffen: false });
      setRueckmeldung({ art: 'ok', text: 'Beauftragt. Das Bild kommt als neue Fassung, sobald der PC es erzeugt hat.' });
      standAbfragen();
    } else {
      setRueckmeldung({ art: 'fehler', text: e.grund });
    }
  };

  const updateData = (d: unknown) => {
    const res = ImagePropsSchema.safeParse(d);
    if (res.success) {
      setData(res.data);
      setErrors(null);
    } else {
      setErrors(res.error);
    }
  };

  return (
    <BaseSidebarPanel title="Bild">
      <Stack spacing={1}>
        {aktuell.startsWith(ANZEIGE) && (
          <Box component="img" src={aktuell} alt="" sx={{ width: '100%', borderRadius: 1, border: 1, borderColor: 'divider' }} />
        )}
        <Typography variant="caption" color="text.secondary">
          {platz
            ? formatText(data.props?.width as number, data.props?.height as number)
            : 'Kein Bildplatz – Breite und Höhe setzen, damit der Agent ein passendes Bild erzeugen kann'}
        </Typography>
        {s.art && (
          <Chip
            size="small"
            label={s.text}
            color={s.art === 'fehler' ? 'error' : s.art === 'laeuft' ? 'info' : 'default'}
            sx={{ alignSelf: 'flex-start', maxWidth: '100%' }}
          />
        )}

        <Typography variant="subtitle2">{knopfText(leer)}</Typography>
        <TextField
          size="small"
          fullWidth
          label="Hinweis (optional)"
          value={hinweis}
          onChange={(ev) => {
            setHinweis(ev.target.value);
            pultStore.setState({ hinweisOffen: ev.target.value.trim() !== '' });
          }}
          inputProps={{ maxLength: 500 }}
        />
        {!leer && (
          <>
            <ToggleButtonGroup
              exclusive
              size="small"
              value={stufe}
              disabled={neu}
              onChange={(_, v: number | null) => {
                if (v !== null) setStufe(v);
              }}
              aria-label="Stärke der Überarbeitung"
            >
              <ToggleButton value={STUFE_NAH}>Nah am Original</ToggleButton>
              <ToggleButton value={STUFE_FREI}>Freier</ToggleButton>
            </ToggleButtonGroup>
            <FormControlLabel
              control={<Checkbox size="small" checked={neu} onChange={(ev) => setNeu(ev.target.checked)} />}
              label="Ganz neu erzeugen"
            />
          </>
        )}
        <Button
          size="small"
          variant="contained"
          sx={{ alignSelf: 'flex-start' }}
          disabled={sperre !== null || laeuft || !start || !selectedBlockId}
          onClick={erzeugen}
        >
          {knopfText(leer)}
        </Button>
        {sperre && (
          <Typography variant="caption" color="text.secondary">
            {sperre}
          </Typography>
        )}
        {rueckmeldung && (
          <Typography variant="body2" color={rueckmeldung.art === 'fehler' ? 'error' : 'text.secondary'}>
            {rueckmeldung.text}
          </Typography>
        )}

        <Typography variant="subtitle2">Aus Medien wählen</Typography>
        {kacheln.length > 0 && (
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1 }}>
            {kacheln.map((n) => {
              const src = ANZEIGE + encodeURIComponent(n);
              const an = n === gewaehlt;
              return (
                <Box
                  key={n}
                  component="img"
                  src={src}
                  alt={n}
                  title={n}
                  loading="lazy"
                  onClick={() => updateData({ ...data, props: { ...data.props, url: src } })}
                  sx={{
                    width: '100%',
                    aspectRatio: '1 / 1',
                    objectFit: 'cover',
                    borderRadius: 1,
                    cursor: 'pointer',
                    outline: an ? '2px solid' : 'none',
                    outlineColor: 'primary.main',
                  }}
                />
              );
            })}
          </Box>
        )}
        <Typography variant="caption" color="text.secondary">
          {medien === null
            ? 'Medien werden geladen …'
            : optionen.length === 0
              ? 'Keine Bilder in den Medien. Bilder im Pult unter Medien hochladen.'
              : 'Erlaubt: png, jpg, jpeg aus den Medien'}
        </Typography>
        {gewaehlt !== '' && (
          <Button
            size="small"
            sx={{ alignSelf: 'flex-start' }}
            onClick={() => updateData({ ...data, props: { ...data.props, url: null } })}
          >
            Kein Bild
          </Button>
        )}
        {fehltInListe && (
          <Typography variant="caption" color="text.secondary">
            {gewaehlt} (nicht mehr in den Medien)
          </Typography>
        )}
        {kaputt && (
          <Typography variant="body2" color="error">
            Bildadresse ungültig. Bitte ein Bild aus den Medien wählen.
          </Typography>
        )}
        {aktuell !== '' && !aktuell.startsWith(ANZEIGE) && (
          <Typography variant="body2" color="error">
            Dieses Bild stammt nicht aus den Medien und wird beim Speichern abgelehnt. Bitte ein Bild aus den
            Medien wählen.
          </Typography>
        )}
        <Button size="small" sx={{ alignSelf: 'flex-start' }} onClick={() => medienLaden(true)}>
          Medienliste neu laden
        </Button>
      </Stack>

      <TextInput
        label="Alternativtext"
        defaultValue={data.props?.alt ?? ''}
        onChange={(alt) => updateData({ ...data, props: { ...data.props, alt } })}
      />
      <TextInput
        label="Link beim Anklicken"
        placeholder="https://…"
        helperText="Optional, nur Adressen mit https://"
        defaultValue={data.props?.linkHref ?? ''}
        onChange={(v) => {
          const linkHref = v.trim().length === 0 ? null : v.trim();
          updateData({ ...data, props: { ...data.props, linkHref } });
        }}
      />
      <Typography variant="caption" color="text.secondary">
        Breite und Höhe bestimmen das Format des Bildplatzes
      </Typography>
      <Stack direction="row" spacing={2}>
        <TextDimensionInput
          label="Breite"
          min={1}
          max={600}
          defaultValue={data.props?.width}
          onChange={(width) => updateData({ ...data, props: { ...data.props, width } })}
        />
        <TextDimensionInput
          label="Höhe"
          min={0}
          max={600}
          defaultValue={data.props?.height}
          onChange={(height) => updateData({ ...data, props: { ...data.props, height } })}
        />
      </Stack>

      <RadioGroupInput
        label="Ausrichtung"
        defaultValue={data.props?.contentAlignment ?? 'middle'}
        onChange={(contentAlignment) => updateData({ ...data, props: { ...data.props, contentAlignment } })}
      >
        <ToggleButton value="top">
          <VerticalAlignTopOutlined fontSize="small" />
        </ToggleButton>
        <ToggleButton value="middle">
          <VerticalAlignCenterOutlined fontSize="small" />
        </ToggleButton>
        <ToggleButton value="bottom">
          <VerticalAlignBottomOutlined fontSize="small" />
        </ToggleButton>
      </RadioGroupInput>

      <MultiStylePropertyPanel
        names={['backgroundColor', 'textAlign', 'padding']}
        value={data.style}
        onChange={(style) => updateData({ ...data, style })}
      />
    </BaseSidebarPanel>
  );
}

