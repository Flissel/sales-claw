import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { SeiteText } from './seiteText';

describe('SeiteText', () => {
  it('escaped, formatiert, nur https-Links', () => {
    const h = renderToStaticMarkup(<SeiteText text={'<b>x</b> **fett** *kursiv* [hier](https://a.de) [böse](javascript:alert(1))'} />);
    expect(h).toContain('&lt;b&gt;');
    expect(h).toContain('<strong>fett</strong>');
    expect(h).toContain('<em>kursiv</em>');
    expect(h).toContain('href="https://a.de"');
    expect(h).not.toContain('javascript:');
    expect(h).toContain('böse');
  });
  it('Zeilenumbruch', () => {
    expect(renderToStaticMarkup(<SeiteText text={'a\nb'} />)).toContain('<br/>');
  });
});
