// Schreibt test/abschnitte.golden.json: Bauplaene der Abschnitte (mit Farb-Marken) und Farbproben.
// Der Marketing-Agent (vibemind-os spaces/marketing/claw/abschnitte.json) nutzt dieselbe Datei.
import { writeFileSync } from 'node:fs';

import { golden } from '../src/abschnitte.ts';

writeFileSync(new URL('../test/abschnitte.golden.json', import.meta.url), JSON.stringify(golden(), null, 1) + '\n');
