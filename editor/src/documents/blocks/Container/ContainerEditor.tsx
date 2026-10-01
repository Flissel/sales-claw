import React from 'react';

import { Container as BaseContainer } from '@usewaypoint/block-container';

import { ANZEIGE } from '../../../pult';
import { useCurrentBlockId } from '../../editor/EditorBlock';
import { setDocument, setSelectedBlockId, useDocument } from '../../editor/EditorContext';
import EditorChildrenIds from '../helpers/EditorChildrenIds';

import { ContainerProps } from './ContainerPropsSchema';

export default function ContainerEditor({ style, props }: ContainerProps) {
  const childrenIds = props?.childrenIds ?? [];

  const document = useDocument();
  const currentBlockId = useCurrentBlockId();

  const kinder = (
    <EditorChildrenIds
      nurInhalt
      childrenIds={childrenIds}
      onChange={({ block, blockId, childrenIds }) => {
        const bisher = document[currentBlockId].data as ContainerProps;
        setDocument({
          [blockId]: block,
          [currentBlockId]: {
            type: 'Container',
            data: {
              ...bisher,
              // Uebrige props (Hintergrundbild url/width/height, grafik) bleiben erhalten.
              props: { ...bisher.props, childrenIds },
            },
          },
        });
        setSelectedBlockId(blockId);
      }}
    />
  );

  const { overlay, ...grundStil } = style ?? {};
  const bild = props?.url;
  if (!bild || !bild.startsWith(ANZEIGE)) {
    return <BaseContainer style={style ? grundStil : style}>{kinder}</BaseContainer>;
  }

  // Hintergrundbild aus den Medien (wie mj-section background-url, cover); die
  // Hintergrundfarbe liegt dahinter, das Farbfeld halbtransparent darueber.
  return (
    <div
      style={{
        position: 'relative',
        backgroundColor: grundStil.backgroundColor ?? undefined,
        backgroundImage: `url("${bild}")`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundRepeat: 'no-repeat',
        borderRadius: grundStil.borderRadius ?? undefined,
        minHeight: props?.height ?? undefined,
      }}
    >
      {overlay && (
        <div
          aria-hidden
          style={{
            position: 'absolute',
            inset: 0,
            backgroundColor: overlay.farbe,
            opacity: overlay.deckkraft / 100,
            borderRadius: grundStil.borderRadius ?? undefined,
            pointerEvents: 'none',
          }}
        />
      )}
      <div style={{ position: 'relative' }}>
        <BaseContainer style={{ ...grundStil, backgroundColor: null }}>{kinder}</BaseContainer>
      </div>
    </div>
  );
}
