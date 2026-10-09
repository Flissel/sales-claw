import React from 'react';

import { Box, Drawer, Tab, Tabs } from '@mui/material';

import { setSidebarTab, useInspectorDrawerOpen, useSelectedSidebarTab } from '../../documents/editor/EditorContext';

import { useInert } from '../Chat/sperren';

import ConfigurationPanel from './ConfigurationPanel';
import StylesPanel from './StylesPanel';

// chat: unter den Block-Eigenschaften (einklappbar, Spec 2026-10-02 §3); gesperrt: der Agent arbeitet.
export default function InspectorDrawer({ chat, gesperrt = false, breite, griff }: { chat?: React.ReactNode; gesperrt?: boolean; breite: number; griff?: React.ReactNode }) {
  const panelRef = useInert<HTMLDivElement>(gesperrt);
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
        width: inspectorDrawerOpen ? breite : 0,
      }}
    >
        {griff}
      <Box sx={{ width: breite, height: 49, flexShrink: 0, borderBottom: 1, borderColor: 'divider' }}>
        <Box px={2}>
          <Tabs value={selectedSidebarTab} onChange={(_, v) => setSidebarTab(v)}>
            <Tab value="styles" label="Gestaltung" />
            <Tab value="block-configuration" label="Block" />
          </Tabs>
        </Box>
      </Box>
      <Box sx={{ width: breite, flex: 1, minHeight: 0, overflow: 'auto' }}>
        {/* inert nur auf dem Inhalt: der Rahmen bleibt scrollbar. */}
        <Box
          ref={panelRef}
          aria-disabled={gesperrt || undefined}
          sx={{ opacity: gesperrt ? 0.45 : 1, pointerEvents: gesperrt ? 'none' : 'auto', transition: 'opacity 150ms ease-out' }}
        >
          {renderCurrentSidebarPanel()}
        </Box>
      </Box>
      {chat && <Box sx={{ width: breite, flexShrink: 0 }}>{chat}</Box>}
    </Drawer>
  );
}
