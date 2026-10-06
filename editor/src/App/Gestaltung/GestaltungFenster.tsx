// Vollbildfenster fuer eine Gestaltungsflaeche (Spec 2026-10-02 §3, Framer-Stil):
// Kopfleiste oben, Ebenen links, Flaeche in der Mitte, Eigenschaften rechts.
// "Zurueck zum Newsletter" prueft, laesst den Server flachrechnen und setzt dann
// gestaltung, url, width, height und alt am Bild-Block.
import React, { useEffect, useMemo, useRef, useState } from 'react';

import { ArrowBackRounded, ErrorOutlineRounded, IosShareRounded, RedoRounded, UndoRounded } from '@mui/icons-material';
import { Box, Button, CircularProgress, IconButton, ThemeProvider, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';

import { getDocument, setSelectedBlockId, useDocument } from '../../documents/editor/EditorContext';
import type { TEditorConfiguration } from '../../documents/editor/core';
import { Format, FORMATE } from '../../gestaltung';
import { gleich } from '../../live';
import { fehlerText, gestaltungRechnen } from '../../pult';
import { gestaltungSchliessen, newsletterSichern, pultStore } from '../../pultZustand';
import { GestaltungSchema } from '../../schemata';

import { FarbFeld } from './Bedienelemente';
import EbenenListe from './EbenenListe';
import Eigenschaften from './Eigenschaften';
import Flaeche, { Hinweisleiste } from './Flaeche';
import { flaecheLesen, formatWechseln, ladenfarben, pruefGrund, quelleAnzeige } from './hilfen';
import { FARBE, gestaltungThema, KOPF_HOEHE, LINKS_BREITE, RECHTS_BREITE, UI_SCHRIFT } from './gestaltungStil';
import { useFensterTasten } from './useFensterTasten';
import { useGestaltung } from './useGestaltung';
import { SperrSchicht, useAgentArbeitet } from '../Chat/Sperre';
import { useInert } from '../Chat/sperren';

// Naht fuer Task 14: mit onExportieren wird "Exportieren…" aktiv, chat erscheint unter den Eigenschaften.
export type GestaltungFensterProps = {
  onExportieren?: () => void;
  chat?: React.ReactNode;
};

const FORMAT_KNOEPFE: Array<[Format, string]> = [
  ['quer', 'Quer'],
  ['quadrat', 'Quadrat'],
  ['hoch', 'Hoch'],
  ['banner', 'Banner'],
];

// Kleines Seitenverhaeltnis-Symbol (max. 16 px) fuer die Format-Segmente.
function FormatSymbol({ f }: { f: Format }) {
  const [a, b] = FORMATE[f];
  const s = 14 / Math.max(a, b);
  return <Box component="span" sx={{ width: a * s, height: b * s, border: '1.5px solid currentColor', borderRadius: '2px', flexShrink: 0 }} />;
}

// Dokument mit geaenderten Props des Bild-Blocks id (fehlt der Block, bleibt alles, wie es ist).
function mitProps(d: TEditorConfiguration, id: string, patch: Record<string, unknown>): TEditorConfiguration {
  const b = d[id];
  if (b?.type !== 'Image') return d;
  return { ...d, [id]: { type: 'Image', data: { ...b.data, props: { ...b.data.props, ...patch } } } };
}

export default function GestaltungFenster(props: GestaltungFensterProps) {
  const offen = pultStore((p) => p.gestaltungOffen);
  const thema = useMemo(gestaltungThema, []);
  if (offen === null) return null;
  return (
    <ThemeProvider theme={thema}>
      <Fenster key={offen} id={offen} {...props} />
    </ThemeProvider>
  );
}

function Fenster({ id, onExportieren, chat }: GestaltungFensterProps & { id: string }) {
  const start = pultStore((p) => p.start);
  const arbeitet = useAgentArbeitet();
  // Sperre auch fuer die Tastatur: Kopfmitte, Ebenen, Flaeche und Eigenschaften sind inert.
  const kopfRef = useInert<HTMLDivElement>(arbeitet !== null);
  const ebenenRef = useInert<HTMLDivElement>(arbeitet !== null);
  const mitteRef = useInert<HTMLDivElement>(arbeitet !== null);
  const eigenschaftenRef = useInert<HTMLDivElement>(arbeitet !== null);
  const [anfang, setAnfang] = useState(() => flaecheLesen(getDocument()[id], getDocument().root));
  const z = useGestaltung(anfang.g);
  const [alt, setAlt] = useState(anfang.alt);
  const [altFehlt, setAltFehlt] = useState(false);
  const [versteckt, setVersteckt] = useState<Set<string>>(() => new Set());
  const [textFokus, setTextFokus] = useState(0);
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const altRef = useRef<HTMLTextAreaElement>(null);
  const wurzel = useRef<HTMLDivElement>(null);
  const farben = useMemo(() => ladenfarben(getDocument().root, z.g), [z.g]);
  const geaendert = z.g !== anfang.g || alt !== anfang.alt;

  // Block weg (z. B. geloescht) oder kein Bild: Fenster schliessen.
  useEffect(() => {
    if (getDocument()[id]?.type !== 'Image') gestaltungSchliessen();
  }, [id]);

  useEffect(() => wurzel.current?.focus(), []);

  // Tab schliessen mit offener, ungesicherter Gestaltung: der Browser fragt nach.
  const geaendertRef = useRef(geaendert);
  geaendertRef.current = geaendert;
  useEffect(() => {
    const warnen = (ev: BeforeUnloadEvent) => {
      if (geaendertRef.current) {
        ev.preventDefault();
        ev.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', warnen);
    return () => window.removeEventListener('beforeunload', warnen);
  }, []);

  useFensterTasten(z, versteckt);

  // Live-Ansicht: aendert der Agent die offene Flaeche (Zwischenstand) oder kommt das echte Dokument
  // zurueck, zeigt das Fenster diesen Stand - schreibgeschuetzt, die Sperre liegt darueber. Eigene,
  // ungesicherte Aenderungen werden nie ueberschrieben. Fehlt die Flaeche nur im Zwischenstand, bleibt
  // das Fenster mit dem letzten Stand und einem Hinweis offen (sie kann nach Stopp/Fehler zurueckkommen).
  const dokument = useDocument();
  const block = dokument[id];
  const gesehen = useRef(block);
  const zwischenstand = pultStore((p) => p.zwischenstand !== null);
  const [entfernt, setEntfernt] = useState(false);
  const laeuftRef = useRef(laeuft);
  laeuftRef.current = laeuft;
  useEffect(() => {
    // Lauf zu Ende und die Flaeche ist auch im echten Dokument nicht (mehr) da: schliessen.
    if (!zwischenstand && block?.type !== 'Image' && !geaendertRef.current && !laeuftRef.current) {
      gestaltungSchliessen();
      return;
    }
    // Jeder Zwischenstand ist ein neues Objekt - nur ein inhaltlich anderer Block zaehlt.
    if (gleich(gesehen.current, block)) return;
    gesehen.current = block;
    if (geaendertRef.current || laeuftRef.current) return;
    if (block?.type !== 'Image') {
      if (pultStore.getState().zwischenstand) setEntfernt(true);
      else gestaltungSchliessen();
      return;
    }
    setEntfernt(false);
    const neu = flaecheLesen(block, dokument.root);
    setAnfang(neu);
    setAlt(neu.alt);
    setAltFehlt(false);
  }, [block, dokument.root, zwischenstand]);

  // Dem Chat melden: ungesicherte Aenderungen (sperrt Senden, haelt das Neuladen auf) und Auswahl.
  useEffect(() => {
    pultStore.setState({ gestaltungGeaendert: geaendert, gestaltungAuswahl: z.auswahl });
  }, [geaendert, z.auswahl]);

  // Ausblenden der ausgewaehlten Ebene hebt die Auswahl auf (Rad/Pfeile wirkten sonst unsichtbar).
  const umschalten = (eid: string) => {
    const neu = new Set(versteckt);
    if (!neu.delete(eid)) {
      neu.add(eid);
      if (z.auswahl === eid) z.waehlen(null);
    }
    setVersteckt(neu);
  };

  const verwerfen = () => {
    if (geaendert && !window.confirm('Änderungen an der Fläche verwerfen?')) return;
    gestaltungSchliessen();
    setSelectedBlockId(id);
  };

  const zurueck = async () => {
    if (laeuft) return;
    z.festschreiben();
    const g = z.aktuell();
    const a = alt.trim();
    if (a === '') {
      setAltFehlt(true);
      setFehler('Alternativtext fehlt – bitte rechts unten beschreiben, was die Fläche zeigt.');
      altRef.current?.focus();
      return;
    }
    const p = GestaltungSchema.safeParse(g);
    if (!p.success) {
      setFehler(pruefGrund(p.error, g));
      return;
    }
    const block = getDocument()[id];
    if (block?.type !== 'Image') {
      gestaltungSchliessen();
      return;
    }
    const gestaltung = p.data;
    const unveraendert = anfang.hatBild && JSON.stringify(gestaltung) === JSON.stringify(anfang.g);
    // Nichts geaendert: nichts zu rechnen und nichts zu speichern.
    if (unveraendert && a === (block.data.props?.alt ?? '')) {
      gestaltungSchliessen();
      setSelectedBlockId(id);
      return;
    }
    if (!start) {
      setFehler('Keine Verbindung zum Pult');
      return;
    }
    setLaeuft(true);
    setFehler(null);
    // Nur der Alt-Text neu: ohne Rechnen speichern. Sonst rechnet der Server zuerst das Bild.
    let patch: Record<string, unknown> = { alt: a };
    let hinweise: string[] = [];
    if (!unveraendert) {
      const r = await gestaltungRechnen(start, gestaltung);
      if (!r.ok) {
        setLaeuft(false);
        setFehler(r.grund);
        return;
      }
      patch = { gestaltung, url: quelleAnzeige(r.url), width: r.width, height: r.height, alt: a };
      hinweise = r.hinweise;
    }
    // Neue Fassung (wie "Speichern" in der Pult-Leiste); der Block aendert sich erst bei Erfolg.
    const e = await newsletterSichern(false, (d) => mitProps(d, id, patch));
    setLaeuft(false);
    if (!e.ok) {
      setFehler(fehlerText(e.grund));
      return;
    }
    const gesichert = `Fläche übernommen und als Fassung ${e.fassung} gespeichert.`;
    pultStore.setState({
      meldung: { platz: id, text: hinweise.length > 0 ? `${gesichert} Hinweise: ${hinweise.join(' · ')}` : gesichert },
    });
    gestaltungSchliessen();
    setSelectedBlockId(id);
  };

  const meldung = entfernt && !fehler ? (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1, fontSize: 12, color: FARBE.warnung }}>
      <ErrorOutlineRounded sx={{ fontSize: 14 }} />
      <span>Der Assistent hat diese Fläche im aktuellen Schritt entfernt – hier siehst du den letzten Stand.</span>
    </Box>
  ) : fehler && (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1, fontSize: 12, color: FARBE.fehler }}>
      <ErrorOutlineRounded sx={{ fontSize: 14 }} />
      <span>{fehler}</span>
      <Button size="small" onClick={verwerfen} sx={{ height: 24, fontSize: 12, color: FARBE.gedaempft, fontWeight: 500 }}>
        Änderungen verwerfen
      </Button>
    </Box>
  );

  return (
    <Box
      ref={wurzel}
      tabIndex={-1}
      data-tasten
      role="dialog"
      aria-modal="true"
      aria-label="Gestaltungsfläche"
      sx={{
        position: 'fixed',
        inset: 0,
        zIndex: 1250, // ueber dem MUI-Drawer (1200), unter Menues/Popovern (1300)
        display: 'grid',
        gridTemplateColumns: `${LINKS_BREITE}px minmax(0, 1fr) ${RECHTS_BREITE}px`,
        gridTemplateRows: `${KOPF_HOEHE}px minmax(0, 1fr)`,
        bgcolor: FARBE.geruest,
        color: FARBE.text,
        fontFamily: UI_SCHRIFT,
        outline: 'none',
        '@keyframes gestaltungAuf': { from: { opacity: 0 }, to: { opacity: 1 } },
        animation: 'gestaltungAuf 150ms ease-out',
        '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
      }}
    >
      {/* Kopfleiste */}
      <Box
        component="header"
        sx={{
          gridColumn: '1 / -1',
          display: 'grid',
          gridTemplateColumns: `${LINKS_BREITE}px minmax(0, 1fr) ${RECHTS_BREITE}px`,
          alignItems: 'center',
          bgcolor: FARBE.panel,
          borderBottom: `1px solid ${FARBE.linie}`,
        }}
      >
        <Box sx={{ px: 1 }}>
          <Button
            onClick={zurueck}
            disabled={laeuft || arbeitet !== null}
            color="inherit"
            startIcon={laeuft ? <CircularProgress size={14} color="inherit" /> : <ArrowBackRounded sx={{ fontSize: 18 }} />}
            sx={{ color: FARBE.text, minWidth: 208, justifyContent: 'flex-start', '&:hover': { bgcolor: FARBE.hover } }}
          >
            {laeuft ? 'Wird gerechnet …' : 'Zurück zum Newsletter'}
          </Button>
        </Box>
        <Box
          ref={kopfRef}
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 2,
            minWidth: 0,
            overflow: 'hidden',
            opacity: arbeitet ? 0.4 : 1,
            pointerEvents: arbeitet ? 'none' : 'auto',
            // Schmal (< 1280 px): Formate nur mit Symbol und Verhaeltnis, "Hintergrund" nur als Farbfeld.
            '@media (max-width: 1279.98px)': { gap: 1, '& .format-name, & .hintergrund-text': { display: 'none' } },
          }}
        >
          <ToggleButtonGroup
            exclusive
            value={z.g.format}
            aria-label="Format"
            onChange={(_, f: Format | null) => {
              if (f) z.setzen(formatWechseln(z.aktuell(), f));
            }}
          >
            {FORMAT_KNOEPFE.map(([f, name]) => {
              const [a, b] = FORMATE[f];
              return (
                <ToggleButton key={f} value={f} aria-label={`${name} ${a}:${b}`} title={`${name} ${a}:${b}`} sx={{ gap: 1, px: 1.5, fontSize: 12, fontWeight: 500, whiteSpace: 'nowrap' }}>
                  <FormatSymbol f={f} />
                  <span className="format-name">{name}</span>
                  <Box component="span" sx={{ color: FARBE.gedaempft, fontVariantNumeric: 'tabular-nums' }}>
                    {a}:{b}
                  </Box>
                </ToggleButton>
              );
            })}
          </ToggleButtonGroup>
          <Box sx={{ width: '1px', height: 24, bgcolor: FARBE.linie }} />
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography className="hintergrund-text" sx={{ fontSize: 12, color: FARBE.gedaempft }}>
              Hintergrund
            </Typography>
            <FarbFeld
              kompakt
              label="Hintergrund"
              wert={z.g.hintergrund}
              laden={farben.laden}
              benutzt={farben.benutzt}
              onChange={(v, art) => z.setzen({ ...z.aktuell(), hintergrund: v }, art)}
            />
          </Box>
        </Box>
        <Box sx={{ px: 2, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 0.5 }}>
          <Tooltip title="Rückgängig (Strg+Z)">
            {/* span: Tooltip auch am deaktivierten Knopf */}
            <span>
            <IconButton aria-label="Rückgängig" onClick={z.zurueck} disabled={!z.kannZurueck || arbeitet !== null}>
              <UndoRounded sx={{ fontSize: 18 }} />
            </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Wiederholen (Strg+Y)">
            <span>
            <IconButton aria-label="Wiederholen" onClick={z.vor} disabled={!z.kannVor || arbeitet !== null}>
              <RedoRounded sx={{ fontSize: 18 }} />
            </IconButton>
            </span>
          </Tooltip>
          <Tooltip title={onExportieren ? 'Fläche und Newsletter exportieren' : 'Kommt mit dem Assistenten'}>
            {/* span: ein deaktivierter Knopf loest selbst keine Tooltip-Ereignisse aus */}
            <Box component="span" sx={{ ml: 1 }}>
              <Button variant="contained" disableElevation disabled={!onExportieren} onClick={onExportieren} startIcon={<IosShareRounded sx={{ fontSize: 16 }} />}>
                Exportieren…
              </Button>
            </Box>
          </Tooltip>
        </Box>
      </Box>

      {/* Links: Ebenen */}
      <Box sx={{ bgcolor: FARBE.panel, borderRight: `1px solid ${FARBE.linie}`, minHeight: 0, overflow: 'auto' }}>
        <Box ref={ebenenRef}>
          <EbenenListe z={z} versteckt={versteckt} umschalten={umschalten} />
        </Box>
      </Box>

      {/* Mitte: Flaeche und Hinweise */}
      <Box component="main" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0, overflow: 'auto' }}>
        <Box ref={mitteRef} sx={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, minWidth: 0 }}>
          <Flaeche z={z} versteckt={versteckt} onTextBearbeiten={() => setTextFokus((n) => n + 1)} />
          <Hinweisleiste z={z} meldung={meldung} />
        </Box>
      </Box>

      {/* Waehrend der Agent arbeitet: Ebenen und Flaeche gesperrt (absolut - nimmt keine Rasterzelle) */}
      {arbeitet && <SperrSchicht text={arbeitet} lage={{ position: 'absolute', top: KOPF_HOEHE, left: 0, right: RECHTS_BREITE, bottom: 0, zIndex: 2 }} />}

      {/* Rechts: Eigenschaften, darunter der Chat */}
      <Box component="aside" aria-label="Eigenschaften" sx={{ bgcolor: FARBE.panel, borderLeft: `1px solid ${FARBE.linie}`, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
          <Box ref={eigenschaftenRef} aria-disabled={arbeitet ? true : undefined} sx={{ opacity: arbeitet ? 0.4 : 1, pointerEvents: arbeitet ? 'none' : 'auto', transition: 'opacity 150ms ease-out' }}>
          <Eigenschaften
            z={z}
            farben={farben}
            alt={alt}
            setAlt={(a) => {
              setAlt(a);
              if (a.trim() !== '') setAltFehlt(false);
            }}
            altFehlt={altFehlt}
            altRef={altRef}
            textFokus={textFokus}
          />
          </Box>
        </Box>
        {chat && <Box sx={{ borderTop: `1px solid ${FARBE.linie}`, flexShrink: 0 }}>{chat}</Box>}
      </Box>
    </Box>
  );
}
