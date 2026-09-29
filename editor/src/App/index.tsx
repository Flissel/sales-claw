import React from 'react';

import { Stack, useTheme } from '@mui/material';

import { useInspectorDrawerOpen } from '../documents/editor/EditorContext';

import AbschnittLeiste, { ABSCHNITT_LEISTE_BREITE } from './AbschnittLeiste';
import InspectorDrawer, { INSPECTOR_DRAWER_WIDTH } from './InspectorDrawer';
import TemplatePanel from './TemplatePanel';

function useDrawerTransition(cssProperty: 'margin-left' | 'margin-right', open: boolean) {
  const { transitions } = useTheme();
  return transitions.create(cssProperty, {
    easing: !open ? transitions.easing.sharp : transitions.easing.easeOut,
    duration: !open ? transitions.duration.leavingScreen : transitions.duration.enteringScreen,
  });
}

export default function App() {
  const inspectorDrawerOpen = useInspectorDrawerOpen();

  const marginRightTransition = useDrawerTransition('margin-right', inspectorDrawerOpen);

  return (
    <>
      <AbschnittLeiste />
      <InspectorDrawer />

      <Stack
        sx={{
          marginLeft: `${ABSCHNITT_LEISTE_BREITE}px`,
          marginRight: inspectorDrawerOpen ? `${INSPECTOR_DRAWER_WIDTH}px` : 0,
          transition: marginRightTransition,
        }}
      >
        <TemplatePanel />
      </Stack>
    </>
  );
}
