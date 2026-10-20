// Textauszeichnung der Collage (wie seite_html._inline): **fett**, *kursiv*, [text](https://...), Zeilenumbrueche.
// Nur React-Elemente, nie dangerouslySetInnerHTML; ein Link ausser https zeigt nur seinen Text.
import React, { Fragment, type ReactNode } from 'react';
import { HTTPS } from './seite';

const FETT = /\*\*([^*\n]+?)\*\*/g;
const KURSIV = /\*([^*\n]+?)\*/g;
const TEXTLINK = /\[([^\]]*)\]\(([^)]*)\)/g;

type Macher = (s: string, k: string) => ReactNode;

function umbrueche(t: string, k: string): ReactNode[] {
  return t
    .replace(/\r\n/g, '\n')
    .split('\n')
    .flatMap((zeile, i) => (i === 0 ? [zeile] : [<br key={`${k}b${i}`} />, zeile]));
}

function teile(t: string, re: RegExp, innen: Macher, aussen: Macher, k: string): ReactNode[] {
  const aus: ReactNode[] = [];
  let pos = 0;
  for (const m of t.matchAll(re)) {
    const i = m.index ?? 0;
    if (i > pos) aus.push(aussen(t.slice(pos, i), `${k}a${i}`));
    aus.push(innen(m[1], `${k}i${i}`));
    pos = i + m[0].length;
  }
  if (pos < t.length) aus.push(aussen(t.slice(pos), `${k}z`));
  return aus;
}

const schlicht: Macher = (t, k) => <Fragment key={k}>{umbrueche(t, k)}</Fragment>;
const kursiv: Macher = (t, k) => <em key={k}>{umbrueche(t, k)}</em>;
const fettAussen: Macher = (t, k) => <Fragment key={k}>{teile(t, KURSIV, kursiv, schlicht, k)}</Fragment>;
const fett: Macher = (t, k) => <strong key={k}>{umbrueche(t, k)}</strong>;

function auszeichnung(t: string, k: string): ReactNode {
  return <Fragment key={k}>{teile(t, FETT, fett, fettAussen, k)}</Fragment>;
}

export function SeiteText({ text }: { text: string }): JSX.Element {
  const aus: ReactNode[] = [];
  let pos = 0;
  for (const m of text.matchAll(TEXTLINK)) {
    const i = m.index ?? 0;
    aus.push(auszeichnung(text.slice(pos, i), `t${i}`));
    const [, label, ziel] = m;
    aus.push(
      HTTPS.test(ziel) ? (
        <a key={`l${i}`} href={ziel} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>
          {auszeichnung(label, `ll${i}`)}
        </a>
      ) : (
        auszeichnung(label, `l${i}`)
      ),
    );
    pos = i + m[0].length;
  }
  aus.push(auszeichnung(text.slice(pos), 'ende'));
  return <>{aus}</>;
}
