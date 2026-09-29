import React from 'react';

import { MonitorOutlined, PhoneIphoneOutlined } from '@mui/icons-material';
import { Box, Stack, SxProps, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';

import EditorBlock from '../../documents/editor/EditorBlock';
import { setSelectedScreenSize, useSelectedScreenSize } from '../../documents/editor/EditorContext';
import ToggleInspectorPanelButton from '../InspectorDrawer/ToggleInspectorPanelButton';
import PultLeiste, { PULT_LEISTE_HOEHE } from '../PultLeiste';

// Gegenueber dem Beispiel entfernt: Reiter Vorschau/HTML/JSON, JSON-Import und
// -Download, "Share" und die Vorlagen-Seitenleiste. Die massgebliche Vorschau
// ist die des Pults (Knoepfe "Vorschau Mail"/"Vorschau Handy").
const WERKZEUG_HOEHE = 49;

export default function TemplatePanel() {
  const selectedScreenSize = useSelectedScreenSize();

  let mainBoxSx: SxProps = {
    height: '100%',
  };
  if (selectedScreenSize === 'mobile') {
    mainBoxSx = {
      ...mainBoxSx,
      margin: '32px auto',
      width: 370,
      height: 800,
      boxShadow:
        'rgba(33, 36, 67, 0.04) 0px 10px 20px, rgba(33, 36, 67, 0.04) 0px 2px 6px, rgba(33, 36, 67, 0.04) 0px 0px 1px',
    };
  }

  const handleScreenSizeChange = (_: unknown, value: unknown) => {
    switch (value) {
      case 'mobile':
      case 'desktop':
        setSelectedScreenSize(value);
        return;
      default:
        setSelectedScreenSize('desktop');
    }
  };

  return (
    <>
      <Box sx={{ position: 'sticky', top: 0, zIndex: 'appBar' }}>
        <PultLeiste />
        <Stack
          sx={{
            height: WERKZEUG_HOEHE,
            borderBottom: 1,
            borderColor: 'divider',
            backgroundColor: 'white',
            px: 1,
          }}
          direction="row"
          justifyContent="space-between"
          alignItems="center"
        >
          <Typography variant="body2" color="text.secondary" sx={{ px: 1 }}>
            Block anklicken zum Bearbeiten, „+“ fügt einen neuen Block ein.
          </Typography>
          <Stack direction="row" spacing={2} alignItems="center">
            <ToggleButtonGroup value={selectedScreenSize} exclusive size="small" onChange={handleScreenSizeChange}>
              <ToggleButton value="desktop">
                <Tooltip title="Breite Ansicht">
                  <MonitorOutlined fontSize="small" />
                </Tooltip>
              </ToggleButton>
              <ToggleButton value="mobile">
                <Tooltip title="Schmale Ansicht (Handy)">
                  <PhoneIphoneOutlined fontSize="small" />
                </Tooltip>
              </ToggleButton>
            </ToggleButtonGroup>
            <ToggleInspectorPanelButton />
          </Stack>
        </Stack>
      </Box>
      <Box
        sx={{
          height: `calc(100vh - ${PULT_LEISTE_HOEHE + WERKZEUG_HOEHE}px)`,
          overflow: 'auto',
          minWidth: 370,
        }}
      >
        <Box sx={mainBoxSx}>
          <EditorBlock id="root" />
        </Box>
      </Box>
    </>
  );
}
