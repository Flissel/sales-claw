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

const PLATZ = /(\d+)/;

// Wie seite_html._auszeichnung: erst **fett** herausloesen (Platzhalter ohne Sternchen), dann *kursiv* ueber
// das ganze Ergebnis, damit Kursiv auch eine fette Gruppe umschliessen kann.
function auszeichnung(t: string, k: string): ReactNode {
  const fette: string[] = [];
  const ohne = t.replace(FETT, (_g, inhalt: string) => `${fette.push(inhalt) - 1}`);
  const blatt: Macher = (s, kk) => (
    <Fragment key={kk}>
      {s.split(new RegExp(PLATZ.source, 'g')).map((teil, i) =>
        i % 2 === 0 ? <Fragment key={`${kk}t${i}`}>{umbrueche(teil, `${kk}t${i}`)}</Fragment> : (
          <strong key={`${kk}f${i}`}>{umbrueche(fette[Number(teil)], `${kk}f${i}`)}</strong>
        ),
      )}
    </Fragment>
  );
  const kursiv: Macher = (s, kk) => <em key={kk}>{blatt(s, `${kk}e`)}</em>;
  return <Fragment key={k}>{teile(ohne, KURSIV, kursiv, blatt, k)}</Fragment>;
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
