import React, { Fragment } from 'react';

import { Box } from '@mui/material';

import { TEditorBlock } from '../../../editor/core';
import EditorBlock from '../../../editor/EditorBlock';

import { ABSCHNITTE, AbschnittSchluessel, DRAG_TYP } from '../../../../abschnitte';
import { abschnittEinsetzen } from '../../../../App/AbschnittLeiste';

import AddBlockButton from './AddBlockMenu';

export type EditorChildrenChange = {
  blockId: string;
  block: TEditorBlock;
  childrenIds: string[];
};

function generateId() {
  return `block-${Date.now()}`;
}

// Ablagezone fuer Abschnitte aus der linken Leiste (nur oberste Ebene).
function Ablage({ index }: { index: number }) {
  const [aktiv, setAktiv] = React.useState(false);
  return (
    <Box
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes(DRAG_TYP)) {
          e.preventDefault();
          setAktiv(true);
        }
      }}
      onDragLeave={() => setAktiv(false)}
      onDrop={(e) => {
        setAktiv(false);
        const s = e.dataTransfer.getData(DRAG_TYP) as AbschnittSchluessel;
        if (ABSCHNITTE.some((a) => a.schluessel === s)) {
          e.preventDefault();
          abschnittEinsetzen(s, index);
        }
      }}
      sx={{
        height: aktiv ? 24 : 6,
        my: aktiv ? 1 : 0,
        borderRadius: 1,
        transition: 'all .12s',
        bgcolor: aktiv ? 'primary.main' : 'transparent',
        opacity: aktiv ? 0.35 : 1,
      }}
    />
  );
}
export type EditorChildrenIdsProps = {
  childrenIds: string[] | null | undefined;
  onChange: (val: EditorChildrenChange) => void;
  // true in Rahmen und Spalten: das Menue bietet dort keine Rahmen/Spalten an
  nurInhalt?: boolean;
};
export default function EditorChildrenIds({ childrenIds, onChange, nurInhalt }: EditorChildrenIdsProps) {
  const appendBlock = (block: TEditorBlock) => {
    const blockId = generateId();
    return onChange({
      blockId,
      block,
      childrenIds: [...(childrenIds || []), blockId],
    });
  };

  const insertBlock = (block: TEditorBlock, index: number) => {
    const blockId = generateId();
    const newChildrenIds = [...(childrenIds || [])];
    newChildrenIds.splice(index, 0, blockId);
    return onChange({
      blockId,
      block,
      childrenIds: newChildrenIds,
    });
  };

  if (!childrenIds || childrenIds.length === 0) {
    return (
      <>
        {!nurInhalt && <Ablage index={0} />}
        <AddBlockButton placeholder nurInhalt={nurInhalt} onSelect={appendBlock} />
      </>
    );
  }

  return (
    <>
      {childrenIds.map((childId, i) => (
        <Fragment key={childId}>
          {!nurInhalt && <Ablage index={i} />}
          <AddBlockButton nurInhalt={nurInhalt} onSelect={(block) => insertBlock(block, i)} />
          <EditorBlock id={childId} />
        </Fragment>
      ))}
      {!nurInhalt && <Ablage index={childrenIds.length} />}
      <AddBlockButton nurInhalt={nurInhalt} onSelect={appendBlock} />
    </>
  );
}
