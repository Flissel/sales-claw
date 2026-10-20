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
  it('Kursiv umschliesst fette Gruppe', () => {
    expect(renderToStaticMarkup(<SeiteText text={'*a **b** c*'} />)).toContain('<em>a <strong>b</strong> c</em>');
  });
  it('Ziffern ohne Fett bleiben Text', () => {
    expect(renderToStaticMarkup(<SeiteText text={'Preis 5 Euro'} />)).toBe('Preis 5 Euro');
  });
  it('Ziffer neben Fett', () => {
    expect(renderToStaticMarkup(<SeiteText text={'Tel 0 **b**'} />)).toBe('Tel 0 <strong>b</strong>');
  });
  it('Platzhalterzeichen im Text stoeren nicht', () => {
    const h = renderToStaticMarkup(<SeiteText text={'x0 **b** '} />);
    expect(h).toBe('x0 <strong>b</strong> ');
  });
  it('Zeilenumbruch', () => {
    expect(renderToStaticMarkup(<SeiteText text={'a\nb'} />)).toContain('<br/>');
  });
});
