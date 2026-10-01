import React from 'react';
import { z } from 'zod';

import { Divider, DividerPropsSchema } from '@usewaypoint/block-divider';
import { Spacer, SpacerPropsSchema } from '@usewaypoint/block-spacer';
import {
  buildBlockComponent,
  buildBlockConfigurationDictionary,
  buildBlockConfigurationSchema,
} from '@usewaypoint/document-core';

import ColumnsContainerEditor from '../blocks/ColumnsContainer/ColumnsContainerEditor';
import ColumnsContainerPropsSchema from '../blocks/ColumnsContainer/ColumnsContainerPropsSchema';
import ContainerEditor from '../blocks/Container/ContainerEditor';
import ContainerPropsSchema from '../blocks/Container/ContainerPropsSchema';
import EmailLayoutEditor from '../blocks/EmailLayout/EmailLayoutEditor';
import EmailLayoutPropsSchema from '../blocks/EmailLayout/EmailLayoutPropsSchema';
import EditorBlockWrapper from '../blocks/helpers/block-wrappers/EditorBlockWrapper';
import { VorlagenButton, VorlagenHeading, VorlagenImage, VorlagenText } from '../blocks/Vorlagentext';
import { ButtonSchema, HeadingSchema, ImageSchema, TextSchema } from '../../schemata';

// Platzhalter fuer ein Bild ohne Datei: als data:-Adresse, weil die Seite
// Bilder nur von 'self' und data: laden darf (keine fremden Server).
const BILD_PLATZHALTER =
  'data:image/svg+xml,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="300" viewBox="0 0 600 300">' +
      '<rect width="600" height="300" fill="#F8F8F8"/>' +
      '<text x="300" y="158" font-family="sans-serif" font-size="22" fill="#999" text-anchor="middle">' +
      'Bild aus den Medien wählen</text></svg>'
  );

// Html und Avatar sind absichtlich nicht dabei: die Pruefung im Pult nimmt nur
// Heading, Text, Button, Image, Divider, Spacer, Container, ColumnsContainer an.
const EDITOR_DICTIONARY = buildBlockConfigurationDictionary({
  Button: {
    schema: ButtonSchema,
    Component: (props) => (
      <EditorBlockWrapper>
        <VorlagenButton {...props} />
      </EditorBlockWrapper>
    ),
  },
  Container: {
    schema: ContainerPropsSchema,
    Component: (props) => (
      <EditorBlockWrapper>
        <ContainerEditor {...props} />
      </EditorBlockWrapper>
    ),
  },
  ColumnsContainer: {
    schema: ColumnsContainerPropsSchema,
    Component: (props) => (
      <EditorBlockWrapper>
        <ColumnsContainerEditor {...props} />
      </EditorBlockWrapper>
    ),
  },
  Heading: {
    schema: HeadingSchema,
    Component: (props) => (
      <EditorBlockWrapper>
        <VorlagenHeading {...props} />
      </EditorBlockWrapper>
    ),
  },
  Image: {
    schema: ImageSchema,
    Component: (data) => {
      const props = {
        ...data,
        props: {
          ...data.props,
          url: data.props?.url || BILD_PLATZHALTER,
        },
      };
      return (
        <EditorBlockWrapper>
          <VorlagenImage {...props} />
        </EditorBlockWrapper>
      );
    },
  },
  Text: {
    schema: TextSchema,
    Component: (props) => (
      <EditorBlockWrapper>
        <VorlagenText {...props} />
      </EditorBlockWrapper>
    ),
  },
  EmailLayout: {
    schema: EmailLayoutPropsSchema,
    Component: (p) => <EmailLayoutEditor {...p} />,
  },
  Spacer: {
    schema: SpacerPropsSchema,
    Component: (props) => (
      <EditorBlockWrapper>
        <Spacer {...props} />
      </EditorBlockWrapper>
    ),
  },
  Divider: {
    schema: DividerPropsSchema,
    Component: (props) => (
      <EditorBlockWrapper>
        <Divider {...props} />
      </EditorBlockWrapper>
    ),
  },
});

export const EditorBlock = buildBlockComponent(EDITOR_DICTIONARY);
export const EditorBlockSchema = buildBlockConfigurationSchema(EDITOR_DICTIONARY);
export const EditorConfigurationSchema = z.record(z.string(), EditorBlockSchema);

export type TEditorBlock = z.infer<typeof EditorBlockSchema>;
export type TEditorConfiguration = Record<string, TEditorBlock>;
