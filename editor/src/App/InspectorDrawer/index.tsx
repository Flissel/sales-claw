import React from 'react';

import { Box, Drawer, Tab, Tabs } from '@mui/material';

import { setSidebarTab, useInspectorDrawerOpen, useSelectedSidebarTab } from '../../documents/editor/EditorContext';

import ConfigurationPanel from './ConfigurationPanel';
import StylesPanel from './StylesPanel';

export const INSPECTOR_DRAWER_WIDTH = 320;

// chat: unter den Block-Eigenschaften (einklappbar, Spec 2026-10-02 §3); gesperrt: der Agent arbeitet.
export default function InspectorDrawer({ chat, gesperrt = false }: { chat?: React.ReactNode; gesperrt?: boolean }) {
  const selectedSidebarTab = useSelectedSidebarTab();
  const inspectorDrawerOpen = useInspectorDrawerOpen();

  const renderCurrentSidebarPanel = () => {
    switch (selectedSidebarTab) {
      case 'block-configuration':
        return <ConfigurationPanel />;
      case 'styles':
        return <StylesPanel />;
    }
  };

  return (
    <Drawer
      variant="persistent"
      anchor="right"
      open={inspectorDrawerOpen}
      sx={{
        width: inspectorDrawerOpen ? INSPECTOR_DRAWER_WIDTH : 0,
      }}
    >
      <Box sx={{ width: INSPECTOR_DRAWER_WIDTH, height: 49, flexShrink: 0, borderBottom: 1, borderColor: 'divider' }}>
        <Box px={2}>
          <Tabs value={selectedSidebarTab} onChange={(_, v) => setSidebarTab(v)}>
            <Tab value="styles" label="Gestaltung" />
            <Tab value="block-configuration" label="Block" />
          </Tabs>
        </Box>
      </Box>
      <Box
        aria-disabled={gesperrt || undefined}
        sx={{
          width: INSPECTOR_DRAWER_WIDTH,
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          opacity: gesperrt ? 0.45 : 1,
          pointerEvents: gesperrt ? 'none' : 'auto',
          transition: 'opacity 150ms ease-out',
        }}
      >
        {renderCurrentSidebarPanel()}
      </Box>
      {chat && <Box sx={{ width: INSPECTOR_DRAWER_WIDTH, flexShrink: 0 }}>{chat}</Box>}
    </Drawer>
  );
}
