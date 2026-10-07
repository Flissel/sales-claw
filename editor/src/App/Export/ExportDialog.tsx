// Export-Dialog (Spec 2026-10-02 §6): Auswahl Newsletter und/oder Flaechen, Vorschau der drei
// Flaechen-Varianten (vom Server gerechnet), Dateinamen-Vorschau, "In Medien exportieren"
// sendet bestaetigt: true. Exportiert wird immer die gespeicherte Fassung.
import React, { useEffect, useMemo, useState } from 'react';

import { CheckCircleRounded, ErrorOutlineRounded, IosShareRounded } from '@mui/icons-material';
import { Box, Button, Checkbox, CircularProgress, Dialog, FormControlLabel, ThemeProvider } from '@mui/material';

import { dateiNamen, ExportAuswahl, exportieren, exportVorschau, ExportVorschau, GERAETE, Geraet, titelSlug } from '../../chat';
import { getDocument } from '../../documents/editor/EditorContext';
import { kinderVon } from '../../pult';
import { chatAbfragen, medienLaden, pultStore } from '../../pultZustand';
import { quelleAnzeige } from '../Gestaltung/hilfen';
import { FARBE, gestaltungThema, UI_SCHRIFT } from '../Gestaltung/gestaltungStil';

import { LIEGT_ZUR_FREIGABE, useAgentArbeitet } from '../Chat/Sperre';

// Seitenverhaeltnis der Flaechen-Variante je Geraet (Handy 4:5, Tablet 1:1, PC 3:2).
const SEITEN: Record<Geraet, number> = { handy: 4 / 5, tablet: 1, pc: 3 / 2 };
const VORSCHAU_HOEHE = 88;

type Flaeche = { id: string; name: string };

// Flaechen in Dokument-Reihenfolge (Image-Bloecke mit props.gestaltung).
function flaechenImDokument(): Flaeche[] {
  const doc = getDocument();
  const erg: Flaeche[] = [];
  const gesehen = new Set<string>();
  const besuchen = (id: string) => {
    if (gesehen.has(id)) return;
    gesehen.add(id);
    const b = doc[id];
    if (b?.type === 'Image' && typeof b.data.props?.gestaltung === 'object' && b.data.props.gestaltung !== null) {
      const alt = typeof b.data.props.alt === 'string' ? b.data.props.alt.trim() : '';
      erg.push({ id, name: alt || `Fläche ${erg.length + 1}` });
    }
    for (const k of kinderVon(b)) besuchen(k);
  };
  besuchen('root');
  return erg;
}

// Der Server setzt den Titel des Inhalts in <title>Editor – …</title>.
function seitenTitel(): string {
  return document.title.replace(/^Editor\s*[–-]\s*/u, '');
}

type Ergebnis = { dateien: string[]; newsletter: boolean };

function Vorschaubilder({ bilder }: { bilder: Record<Geraet, string> | null | undefined }) {
  return (
    <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
      {GERAETE.map(([g, name]) => (
        <Box key={g} sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Box
            sx={{
              width: Math.round(VORSCHAU_HOEHE * SEITEN[g]),
              height: VORSCHAU_HOEHE,
              borderRadius: '4px',
              overflow: 'hidden',
              bgcolor: FARBE.feld,
              border: `1px solid ${FARBE.linie}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {bilder === undefined ? (
              <CircularProgress size={14} sx={{ color: FARBE.gedaempft }} />
            ) : bilder ? (
              <img src={quelleAnzeige(bilder[g])} alt={`${name}-Variante`} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
            ) : null}
          </Box>
          <Box sx={{ fontSize: 11, color: FARBE.gedaempft }}>{name}</Box>
        </Box>
      ))}
    </Box>
  );
}

export type ExportDialogProps = { offen: boolean; vorbelegt: ExportAuswahl | null; onClose: () => void };

export default function ExportDialog({ offen, vorbelegt, onClose }: ExportDialogProps) {
  const thema = useMemo(gestaltungThema, []);
  return (
    <ThemeProvider theme={thema}>
      <Dialog
        open={offen}
        onClose={onClose}
        maxWidth={false}
        PaperProps={{ sx: { width: 600, maxWidth: 'calc(100vw - 32px)', bgcolor: FARBE.panel, backgroundImage: 'none', border: `1px solid ${FARBE.linie}`, borderRadius: '12px', fontFamily: UI_SCHRIFT } }}
      >
        {offen && <Inhalt vorbelegt={vorbelegt} onClose={onClose} />}
      </Dialog>
    </ThemeProvider>
  );
}

function Inhalt({ vorbelegt, onClose }: { vorbelegt: ExportAuswahl | null; onClose: () => void }) {
  const start = pultStore((p) => p.start);
  const basis = pultStore((p) => p.basis);
  const ungesichert = pultStore((p) => p.ungespeichert || p.gestaltungGeaendert);
  const nurLesen = pultStore((p) => p.nurLesen);
  // Agent/Export am PC ODER Liegt-zur-Freigabe sperren den Export.
  const arbeitet = useAgentArbeitet() ?? (nurLesen ? LIEGT_ZUR_FREIGABE : null);
  const [flaechen] = useState(flaechenImDokument);
  const [newsletter, setNewsletter] = useState(vorbelegt?.newsletter ?? true);
  const [gewaehlt, setGewaehlt] = useState<Set<string>>(() => new Set((vorbelegt?.flaechen ?? []).filter((id) => flaechen.some((f) => f.id === id))));
  // undefined = laedt, null = fehlgeschlagen (Grund in vorschauFehler)
  const [vorschau, setVorschau] = useState<Record<string, Record<Geraet, string> | null>>({});
  const [vorschauFehler, setVorschauFehler] = useState<Record<string, string>>({});
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [ergebnis, setErgebnis] = useState<Ergebnis | null>(null);

  // Je Flaeche eine eigene Vorschau: eine noch nicht gespeicherte Flaeche verdirbt die anderen nicht.
  useEffect(() => {
    if (!start) return;
    let aktiv = true;
    for (const f of flaechen) {
      void exportVorschau(start, [f.id]).then((r) => {
        if (!aktiv) return;
        const bilder: ExportVorschau[string] | undefined = r.ok ? r.flaechen[f.id] : undefined;
        setVorschau((v) => ({ ...v, [f.id]: bilder ?? null }));
        if (!bilder) setVorschauFehler((v) => ({ ...v, [f.id]: r.ok ? 'Keine Vorschau' : r.grund }));
      });
    }
    return () => {
      aktiv = false;
    };
  }, [start, flaechen]);

  const auswahl: ExportAuswahl = { newsletter, flaechen: flaechen.filter((f) => gewaehlt.has(f.id)).map((f) => f.id) };
  const namen = dateiNamen(titelSlug(seitenTitel()), auswahl);
  const leer = !auswahl.newsletter && auswahl.flaechen.length === 0;

  const umschalten = (id: string) => {
    const neu = new Set(gewaehlt);
    if (!neu.delete(id)) neu.add(id);
    setGewaehlt(neu);
  };

  const los = async () => {
    if (!start || leer || laeuft) return;
    setLaeuft(true);
    setFehler(null);
    const r = await exportieren(start, auswahl);
    setLaeuft(false);
    if (!r.ok) {
      setFehler(r.grund);
      return;
    }
    setErgebnis({ dateien: r.dateien, newsletter: r.auftrag !== null });
    if (r.dateien.length > 0) medienLaden(true);
    // Der Newsletter-Export ist ein Auftrag am PC: er sperrt wie der Agent, bis er fertig ist.
    if (r.auftrag !== null) chatAbfragen();
  };

  const abschnitt = { px: 3, py: 2, borderTop: `1px solid ${FARBE.linie}` } as const;
  const haken = { '& .MuiFormControlLabel-label': { fontSize: 13, fontWeight: 500 } } as const;

  return (
    <Box sx={{ color: FARBE.text, fontFamily: UI_SCHRIFT }}>
      <Box sx={{ px: 3, pt: 2.5, pb: 2, display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <IosShareRounded sx={{ fontSize: 18, color: FARBE.akzent }} />
        <Box component="h2" sx={{ m: 0, fontSize: 16, fontWeight: 600 }}>
          Exportieren
        </Box>
        <Box component="span" sx={{ ml: 'auto', fontSize: 12, color: FARBE.gedaempft, fontVariantNumeric: 'tabular-nums' }}>
          gespeicherte Fassung {basis}
        </Box>
      </Box>

      {ergebnis ? (
        <Box sx={{ ...abschnitt, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, fontSize: 13 }}>
            <CheckCircleRounded sx={{ fontSize: 18, color: FARBE.akzent }} />
            {ergebnis.dateien.length > 0 ? `${ergebnis.dateien.length} Dateien liegen jetzt in den Medien:` : 'Export beauftragt.'}
          </Box>
          {ergebnis.dateien.length > 0 && (
            <Box component="ul" sx={{ m: 0, pl: 3.5, fontSize: 12, color: FARBE.gedaempft, fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace', lineHeight: 1.7 }}>
              {ergebnis.dateien.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </Box>
          )}
          {ergebnis.newsletter && (
            <Box sx={{ fontSize: 13, color: FARBE.text, bgcolor: FARBE.feld, borderRadius: '8px', px: 1.5, py: 1 }}>
              Newsletter-Bilder werden am PC gerechnet – sie erscheinen gleich in den Medien.
            </Box>
          )}
        </Box>
      ) : (
        <>
          {ungesichert && (
            <Box sx={{ mx: 3, mb: 2, fontSize: 12, lineHeight: 1.5, color: FARBE.warnung }}>
              Exportiert wird die gespeicherte Fassung – ungesicherte Änderungen sind darin noch nicht enthalten.
            </Box>
          )}
          <Box sx={abschnitt}>
            <FormControlLabel sx={haken} control={<Checkbox size="small" checked={newsletter} onChange={(e) => setNewsletter(e.target.checked)} />} label="Newsletter (Handy, Tablet, PC)" />
            <Box sx={{ pl: 4, fontSize: 12, color: FARBE.gedaempft }}>375 · 768 · 1200 px breit, ganze Länge – wird am PC gerechnet</Box>
          </Box>
          {flaechen.map((f) => (
            <Box key={f.id} sx={abschnitt}>
              <FormControlLabel
                sx={haken}
                control={<Checkbox size="small" checked={gewaehlt.has(f.id)} onChange={() => umschalten(f.id)} />}
                label={
                  <span>
                    {f.name} <Box component="span" sx={{ color: FARBE.gedaempft, fontWeight: 400, fontSize: 12 }}>· {f.id}</Box>
                  </span>
                }
              />
              <Box sx={{ pl: 4 }}>
                <Vorschaubilder bilder={vorschau[f.id]} />
                {vorschauFehler[f.id] && <Box sx={{ fontSize: 12, color: FARBE.gedaempft, mt: 0.5 }}>{vorschauFehler[f.id]}</Box>}
              </Box>
            </Box>
          ))}
          <Box sx={abschnitt}>
            <Box sx={{ fontSize: 12, color: FARBE.gedaempft, mb: 0.75 }}>Dateinamen (vorhandene Namen bekommen -2, -3 …)</Box>
            <Box sx={{ minHeight: 20, fontSize: 12, fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace', color: leer ? FARBE.gedaempft : FARBE.text, lineHeight: 1.7, overflowWrap: 'anywhere' }}>
              {leer ? 'Nichts ausgewählt' : namen.join('  ')}
            </Box>
          </Box>
        </>
      )}

      <Box sx={{ ...abschnitt, display: 'flex', alignItems: 'center', gap: 1 }}>
        {fehler && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, fontSize: 12, color: FARBE.fehler, mr: 'auto' }}>
            <ErrorOutlineRounded sx={{ fontSize: 14 }} />
            {fehler}
          </Box>
        )}
        {!fehler && arbeitet && !ergebnis && <Box sx={{ fontSize: 12, color: FARBE.gedaempft, mr: 'auto' }}>{arbeitet}</Box>}
        <Box sx={{ ml: 'auto', display: 'flex', gap: 1 }}>
          <Button onClick={onClose} color="inherit" sx={{ color: FARBE.gedaempft, '&:hover': { color: FARBE.text, bgcolor: FARBE.hover } }}>
            {ergebnis ? 'Fertig' : 'Abbrechen'}
          </Button>
          {!ergebnis && (
            <Button
              variant="contained"
              disableElevation
              disabled={leer || laeuft || arbeitet !== null}
              onClick={() => void los()}
              startIcon={laeuft ? <CircularProgress size={14} color="inherit" /> : <IosShareRounded sx={{ fontSize: 16 }} />}
            >
              In Medien exportieren
            </Button>
          )}
        </Box>
      </Box>
    </Box>
  );
}
