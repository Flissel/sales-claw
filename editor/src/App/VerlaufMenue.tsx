// Fassungsverlauf in der Pult-Leiste (Plan 2026-10-19 E12): die letzten 30 Fassungen mit
// "Ansehen" (Pult-Vorschau im neuen Tab) und "Wiederherstellen …" (alte Fassung als neue Fassung).
import React, { useState } from 'react';

import { HistoryOutlined, RestoreOutlined, VisibilityOutlined } from '@mui/icons-material';
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  ListItemIcon,
  ListSubheader,
  Menu,
  MenuItem,
  Tooltip,
  Typography,
} from '@mui/material';

import { datumKurz, fassungWiederherstellen, FassungInfo, Start } from '../pult';
import { LIEGT_ZUR_FREIGABE, pultStore } from '../pultZustand';

const SCHMAL = '@media (max-width: 1439.98px)';

export function fassungZeile(f: FassungInfo): string {
  return `Fassung ${f.fassung} · ${f.urheber === 'agent' ? 'Agent' : 'du'} · ${datumKurz(f.erstellt_am, true)}`;
}

export function verlaufVorschauUrl(s: Pick<Start, 'vorschau_url'>, fassung: number): string {
  const trenner = s.vorschau_url.includes('?') ? '&' : '?';
  return `${s.vorschau_url}${trenner}fassung=${fassung}&format=mail`;
}

type Lage = { ungespeichert: boolean; nurLesen: boolean; agent: string | null };

// Ob eine Fassung "Wiederherstellen …" bekommt: alle aelteren. Die neueste nicht - sie ist ja offen.
export function wiederherstellenSichtbar(f: FassungInfo, neueste: number): boolean {
  return f.fassung < neueste;
}

// Warum diese (aeltere) Fassung gerade nicht wiederhergestellt werden kann (null = frei). Das alte
// Format steht gesperrt mit Grund im Menue statt zu fehlen - sonst sieht es aus, als fehle der Eintrag.
export function wiederherstellenSperre(f: FassungInfo, l: Lage): string | null {
  if (f.format !== 'bloecke') return 'Altes Format – lässt sich hier nicht wiederherstellen';
  if (l.nurLesen) return LIEGT_ZUR_FREIGABE;
  if (l.agent !== null) return 'Gesperrt, bis der Assistent fertig ist';
  if (l.ungespeichert) return 'Erst speichern';
  return null;
}

export function wiederherstellenText(fassung: number, basis: number): string {
  return `Fassung ${fassung} als neue Fassung wiederherstellen? Deine jetzige Fassung ${basis} bleibt im Verlauf.`;
}

export default function VerlaufMenue({ agent }: { agent: string | null }) {
  const start = pultStore((p) => p.start);
  const basis = pultStore((p) => p.basis);
  const ungespeichert = pultStore((p) => p.ungespeichert);
  const nurLesen = pultStore((p) => p.nurLesen);
  const [anker, setAnker] = useState<HTMLElement | null>(null);
  const [frage, setFrage] = useState<{ fassung: number; grund: string | null; laeuft: boolean } | null>(null);

  if (!start?.fassungen) return null;
  const fassungen = start.fassungen;
  // Die neueste bekannte Fassung: aus der Liste oder die eben gespeicherte (basis).
  const neueste = Math.max(basis, ...fassungen.map((f) => f.fassung));
  const lage: Lage = { ungespeichert, nurLesen, agent };

  const wiederherstellen = async () => {
    if (!frage) return;
    setFrage({ ...frage, grund: null, laeuft: true });
    const e = await fassungWiederherstellen(start, frage.fassung, pultStore.getState().basis);
    if (e.ok) {
      window.location.reload();
      return;
    }
    setFrage({ ...frage, grund: e.grund, laeuft: false });
  };

  return (
    <>
      <Tooltip title="Frühere Fassungen ansehen oder wiederherstellen" describeChild>
        <Button
          size="small"
          variant="outlined"
          startIcon={<HistoryOutlined />}
          onClick={(ev) => setAnker(ev.currentTarget)}
          aria-label="Verlauf"
          aria-haspopup="menu"
          sx={{
            flexShrink: 0,
            whiteSpace: 'nowrap',
            // Unter 1440 px nur das Symbol: sonst laeuft Zeile 1 neben offenem Chat ueber ("Vorschau" abgeschnitten).
            [SCHMAL]: { minWidth: 0, px: 1, '& .MuiButton-startIcon': { m: 0 }, '& .verlauf-text': { display: 'none' } },
          }}
        >
          <span className="verlauf-text">Verlauf</span>
        </Button>
      </Tooltip>
      <Menu
        anchorEl={anker}
        open={anker !== null}
        onClose={() => setAnker(null)}
        slotProps={{ paper: { sx: { maxHeight: 'min(560px, 70vh)', minWidth: 300 } } }}
      >
        {fassungen.length === 0 && <MenuItem disabled>Noch keine Fassungen</MenuItem>}
        {fassungen.flatMap((f, i) => {
          const sperre = wiederherstellenSperre(f, lage);
          const zeigen = wiederherstellenSichtbar(f, neueste);
          return [
            i > 0 ? <Divider key={`t${f.fassung}`} component="li" /> : null,
            <ListSubheader key={`k${f.fassung}`} sx={{ lineHeight: '32px', bgcolor: 'background.paper' }}>
              {fassungZeile(f)}
              {f.fassung === basis ? ' · offen' : ''}
            </ListSubheader>,
            <MenuItem
              key={`a${f.fassung}`}
              dense
              onClick={() => {
                setAnker(null);
                window.open(verlaufVorschauUrl(start, f.fassung), '_blank', 'noopener');
              }}
            >
              <ListItemIcon>
                <VisibilityOutlined fontSize="small" />
              </ListItemIcon>
              Ansehen
            </MenuItem>,
            zeigen ? (
              <MenuItem
                key={`w${f.fassung}`}
                dense
                disabled={sperre !== null}
                onClick={() => {
                  setAnker(null);
                  setFrage({ fassung: f.fassung, grund: null, laeuft: false });
                }}
              >
                <ListItemIcon>
                  <RestoreOutlined fontSize="small" />
                </ListItemIcon>
                Wiederherstellen …
                {sperre && (
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    ({sperre})
                  </Typography>
                )}
              </MenuItem>
            ) : null,
          ];
        })}
      </Menu>
      <Dialog open={frage !== null} onClose={() => !frage?.laeuft && setFrage(null)}>
        <DialogTitle>Fassung wiederherstellen?</DialogTitle>
        <DialogContent>
          <DialogContentText>{frage && wiederherstellenText(frage.fassung, basis)}</DialogContentText>
          {frage?.grund && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {frage.grund}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button disabled={frage?.laeuft} onClick={() => setFrage(null)}>
            Abbrechen
          </Button>
          <Button
            variant="contained"
            disabled={frage?.laeuft || ungespeichert || nurLesen || agent !== null}
            onClick={() => void wiederherstellen()}
          >
            {frage?.laeuft ? 'Wird wiederhergestellt …' : 'Wiederherstellen'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
