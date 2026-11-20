/**
 * sales-claw pause patch — L2/L3 tests for the recording pause (acts.v1 `pause` / `resume`).
 *
 * Added on top of @vexa/bot from vexaai/vexa-lite:v0.12.28 (Apache-2.0). Proves:
 *   • PauseGate: the pause window starts at the CLICK time (`at`), stays forbidden after resume,
 *     a second `pause` keeps the first click time;
 *   • pipeline: while paused no audio reaches the stt port (and the lane is fed silence), a result
 *     for audio at/after `at` is never published (even from a call started before the pause), and
 *     segments already published with start ≥ at are retracted — on the mixed (jitsi) lane AND the
 *     per-channel (gmeet) lane;
 *   • orchestrator: a `pause` act drives the gate and confirms over lifecycle.v1 with
 *     `aufnahme_pause` — also from the lobby, before the pipeline starts; extra fields are ignored.
 * Run: npx tsx src/pause-gate.test.ts
 */
import Ajv2020, { type ValidateFunction } from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { PauseGate, gateTranscriptSink } from './pause-gate.js';
import { createBotPipeline } from './pipeline.js';
import { createOrchestrator } from './orchestrator.js';
import { parseAct, type Act, type LifecycleEvent, type TranscriptSegment } from './contracts.js';
import type { Invocation } from './config.js';
import type { JoinDriver, JoinOutcome, LifecycleSink, Pipeline, TranscriptSink } from './ports.js';
import type { TranscriptionResult } from '@vexa/transcribe-whisper';
import type { ChunkedTranscriberCallbacks } from '@vexa/mixed-pipeline';
import { noopAloneness, noopActs } from './test-doubles.js';

let failed = 0;
const check = (name: string, cond: boolean, detail = '') => {
  console.log(`  ${cond ? '✅' : '❌'} ${name}${cond ? '' : '  — ' + detail}`);
  if (!cond) failed++;
};
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ── lifecycle.v1 validator (ajv against the PUBLISHED schema, like orchestrator.test.ts) ──
const HERE = dirname(fileURLToPath(import.meta.url));
const LIFECYCLE_SCHEMA = join(HERE, '..', '..', '..', 'contracts', 'lifecycle.v1', 'lifecycle.schema.json');
const lcSchema = JSON.parse(readFileSync(LIFECYCLE_SCHEMA, 'utf8'));
const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema(lcSchema);
const validateLifecycle: ValidateFunction = ajv.compile({ $ref: `${lcSchema.$id}#/$defs/LifecycleEvent` });

/** A test clock the gate reads (epoch ms). */
const clock = (start: number) => {
  const c = { t: start, now: () => c.t };
  return c;
};

function captureSink(): TranscriptSink & { readonly published: TranscriptSegment[]; readonly retracted: string[] } {
  const published: TranscriptSegment[] = [];
  const retracted: string[] = [];
  return { published, retracted, async publish(seg) { published.push(seg); }, async retract(ids) { retracted.push(...ids); } };
}

const baseInv = (over: Partial<Invocation> = {}): Invocation => ({
  platform: 'jitsi', meetingUrl: 'https://meet.ffmuc.net/abc', botName: 'Vexa',
  redisUrl: 'redis://localhost:6379', transcribeEnabled: true, connectionId: 'sess-uid',
  container_name: 'mtg-abc-bot', nativeMeetingId: 'abc', ...over,
});

const seg = (id: string, startS: number, endS = startS + 0.05): TranscriptSegment => ({
  segment_id: id, speaker: 'Alice', text: 'x', start: startS, end: endS, completed: true,
});

async function gateUnit(): Promise<void> {
  console.log('PauseGate');
  {
    const c = clock(2000);
    const g = new PauseGate(c.now);
    check('fresh gate: audio allowed, not paused', g.allowsAudio() && g.pausedSince === null);
    g.pause(1000);
    check('pause(1000): allowsAudio() false', g.allowsAudio() === false);
    check('pause(1000): pausedSince is the click time', g.pausedSince === 1000, String(g.pausedSince));
    check('pause(1000): allowsSegment(0.999) true (before the click)', g.allowsSegment(0.999) === true);
    check('pause(1000): allowsSegment(1.0) false (at the click)', g.allowsSegment(1.0) === false);
    check('pause(1000): allowsSegment(5) false (after the click)', g.allowsSegment(5) === false);
    // R4 ("lieber weg / ganzen Satz loeschen"): a segment that starts before the click but ends after it goes too.
    check('R4 pause(1000): allowsSegment(0.5, 1.2) false (straddles the click)', g.allowsSegment(0.5, 1.2) === false);
    check('R4 pause(1000): allowsSegment(0.5, 0.9) true (ends before the click)', g.allowsSegment(0.5, 0.9) === true);
    check('R4 pause(1000): allowsSegment(0.5, 1.0) true (ends exactly at the click)', g.allowsSegment(0.5, 1.0) === true);
    c.t = 3000;
    g.resume();
    check('resume(): allowsAudio() true', g.allowsAudio() === true);
    check('resume(): pausedSince null', g.pausedSince === null);
    check('resume() at 3000: allowsSegment(5) true', g.allowsSegment(5) === true);
    check('resume() at 3000: allowsSegment(1.5) stays false (inside the closed window)', g.allowsSegment(1.5) === false);
    check('resume() at 3000: allowsSegment(1.0) stays false', g.allowsSegment(1.0) === false);
    check('resume() at 3000: allowsSegment(3.0) true (window end is exclusive)', g.allowsSegment(3.0) === true);
    check('resume() at 3000: allowsSegment(0.5) true (before the window)', g.allowsSegment(0.5) === true);
    check('R4 resume() at 3000: allowsSegment(0.5, 1.5) false (straddles the closed window start)', g.allowsSegment(0.5, 1.5) === false);
    check('R4 resume() at 3000: allowsSegment(2.5, 3.5) false (straddles the resume)', g.allowsSegment(2.5, 3.5) === false);
    check('R4 resume() at 3000: allowsSegment(3.0, 4.0) true (starts at the resume)', g.allowsSegment(3.0, 4.0) === true);
  }
  {
    const c = clock(10_000);
    const g = new PauseGate(c.now);
    g.pause(4000);
    c.t = 11_000;
    g.pause(9000);
    check('pause twice: pausedSince stays the FIRST click time', g.pausedSince === 4000, String(g.pausedSince));
    check('pause twice: 5 s still forbidden', g.allowsSegment(5) === false);
  }
  {
    const c = clock(5000);
    const g = new PauseGate(c.now);
    g.pause(Number.NaN);
    check('pause without a usable click time: pauses NOW (never later)', g.pausedSince === 5000, String(g.pausedSince));
    const g2 = new PauseGate(c.now);
    g2.pause(9000);
    check('click time in the future (clock skew): clamped to now', g2.pausedSince === 5000, String(g2.pausedSince));
  }
  {
    const c = clock(1000);
    const g = new PauseGate(c.now);
    const seen: number[] = [];
    g.onPause((at) => seen.push(at));
    g.pause(800);
    g.pause(900);
    check('onPause fires once per pause, with the click time', seen.length === 1 && seen[0] === 800, JSON.stringify(seen));
    g.resume();
    g.resume();
    check('resume when not paused is a no-op', g.allowsAudio() && g.pausedSince === null);
  }
}

async function sinkUnit(): Promise<void> {
  console.log('gateTranscriptSink');
  const c = clock(100_000);
  const g = new PauseGate(c.now);
  const inner = captureSink();
  const sink = gateTranscriptSink(inner, g, { now: c.now });
  await sink.publish(seg('old', 50));        // published 50 s before the click → outside the 30 s memory
  c.t = 140_000;
  await sink.publish(seg('a', 95));
  await sink.publish(seg('straddle', 99.5, 100.5));
  await sink.publish(seg('b', 101));
  await sink.publish(seg('c', 120));
  check('not paused: everything is published', inner.published.length === 5);
  c.t = 141_000;
  g.pause(100_000);
  await sleep(5);
  check('pause(at): published segments with start ≥ at are retracted',
    inner.retracted.includes('b') && inner.retracted.includes('c'), JSON.stringify(inner.retracted));
  check('R4 pause(at): a published segment straddling the click (end > at) is retracted',
    inner.retracted.includes('straddle'), JSON.stringify(inner.retracted));
  check('pause(at): segments before the click stay', !inner.retracted.includes('a') && !inner.retracted.includes('old'));
  await sink.publish(seg('late', 100.5));
  await sink.publish(seg('pre', 99.9, 99.95));
  await sink.publish(seg('straddle-late', 99.8, 100.2));
  check('paused: a result for audio after the click is dropped', !inner.published.some((s) => s.segment_id === 'late'));
  check('R4 paused: a result straddling the click is dropped', !inner.published.some((s) => s.segment_id === 'straddle-late'));
  check('paused: a result for audio before the click still publishes', inner.published.some((s) => s.segment_id === 'pre'));
  await sink.retract?.(['pre']);
  check('retract passes through', inner.retracted.includes('pre'));
}

async function pipelineMixed(): Promise<void> {
  console.log('pipeline: mixed (jitsi) lane');
  const c = clock(1_000_000);
  const gate = new PauseGate(c.now);
  let calls = 0;
  let release: ((r: TranscriptionResult) => void) | null = null;
  const transcribe = (): Promise<TranscriptionResult> => {
    calls++;
    return new Promise((res) => { release = res; });
  };
  let cb: ChunkedTranscriberCallbacks | null = null;
  const fed: Float32Array[] = [];
  const sink = captureSink();
  const pipe = createBotPipeline(baseInv(), sink, {
    transcribe,
    pauseGate: gate,
    createMixedTranscriber: async (callbacks) => {
      cb = callbacks;
      return { feedAudio(pcm: Float32Array) { fed.push(pcm); }, recordHint() { /* */ }, async dispose() { /* */ } };
    },
  });
  await pipe.start();
  check('mixed: transcriber factory wired', !!cb);

  const voice = new Float32Array(320).fill(0.3);
  pipe.feedMixedAudio(voice, 999_000);
  check('not paused: audio reaches the lane unchanged', fed[0]?.[0] === voice[0]);

  // A segment published BEFORE the act arrives, for audio after the click (at = 1_000_000).
  cb!.publish('Alice', [{ text: 'vorher', startMs: 998_000, endMs: 999_500, language: 'de', segmentId: 't:1:0' }], []);
  cb!.publish('Alice', [{ text: 'ueber den Klick', startMs: 999_600, endMs: 1_000_400, language: 'de', segmentId: 't:1:s' }], []);
  cb!.publish('Alice', [{ text: 'nach Klick', startMs: 1_000_500, endMs: 1_001_000, language: 'de', segmentId: 't:2:0' }],
    [{ text: 'entwurf', startMs: 1_001_000, endMs: 1_001_500, language: 'de', segmentId: 't:2:p' }]);
  await sleep(5);

  // A transcribe call started BEFORE the pause, resolving AFTER it.
  const inFlight = cb!.transcribe(new Float32Array(16000), undefined);
  check('not paused: the stt port is called', calls === 1, String(calls));

  c.t = 1_002_000;
  gate.pause(1_000_000);
  await sleep(5);
  check('pause: already-published segments with start ≥ at are retracted',
    sink.retracted.includes('t:2:0') && sink.retracted.includes('t:2:p'), JSON.stringify(sink.retracted));
  check('R4 pause: an already-published segment straddling the click is retracted (whole sentence)',
    sink.retracted.includes('t:1:s'), JSON.stringify(sink.retracted));
  check('pause: the segment before the click is not retracted', !sink.retracted.includes('t:1:0'));

  // Raced against a timer: a gate that forwarded to the (pending) mock must FAIL, not hang.
  const during = await Promise.race([cb!.transcribe(new Float32Array(16000), 'prompt'), sleep(50).then(() => null)]);
  check('paused: transcribe is NOT called', calls === 1, String(calls));
  check('paused: the stt port answers at once with an empty result',
    during !== null && during.text === '' && during.segments.length === 0, JSON.stringify(during));

  pipe.feedMixedAudio(voice, 1_002_100);
  const last = fed[fed.length - 1];
  check('paused: the lane is fed silence, never the captured audio',
    fed.length === 2 && last.length === voice.length && last.every((v) => v === 0));

  release!({ text: 'spaet', language: 'de', duration: 1, segments: [] });
  await inFlight;
  // The lane maps the late result into segments — one for audio after the click, one before.
  cb!.publish('Alice', [
    { text: 'spaet nach Klick', startMs: 1_000_200, endMs: 1_000_900, language: 'de', segmentId: 't:3:0' },
    { text: 'spaet vor Klick', startMs: 999_000, endMs: 999_900, language: 'de', segmentId: 't:4:0' },
    { text: 'spaet ueber den Klick', startMs: 999_900, endMs: 1_000_300, language: 'de', segmentId: 't:4:s' },
  ], []);
  await sleep(5);
  check('R4 in-flight result straddling the click is never published',
    !sink.published.some((s) => s.segment_id === 't:4:s'));
  check('in-flight result for audio at/after the click is never published',
    !sink.published.some((s) => s.segment_id === 't:3:0'));
  check('in-flight result for audio before the click is published', sink.published.some((s) => s.segment_id === 't:4:0'));

  c.t = 1_005_000;
  gate.resume();
  pipe.feedMixedAudio(voice, 1_005_100);
  check('resume: captured audio reaches the lane again', fed[fed.length - 1]?.[0] === voice[0]);
  const afterResume = cb!.transcribe(new Float32Array(16000), undefined);
  check('resume: the stt port is called again', calls === 2, String(calls));
  release!({ text: '', language: 'de', duration: 0, segments: [] });
  await afterResume;
  cb!.publish('Alice', [
    { text: 'in der Pause', startMs: 1_003_000, endMs: 1_004_000, language: 'de', segmentId: 't:5:0' },
    { text: 'ueber das Weiter', startMs: 1_004_500, endMs: 1_005_500, language: 'de', segmentId: 't:5:s' },
    { text: 'danach', startMs: 1_005_200, endMs: 1_006_000, language: 'de', segmentId: 't:6:0' },
  ], []);
  await sleep(5);
  check('R4 resume: a segment straddling the resume stays dropped', !sink.published.some((s) => s.segment_id === 't:5:s'));
  check('resume: a segment inside the paused window stays dropped', !sink.published.some((s) => s.segment_id === 't:5:0'));
  check('resume: a segment after the resume publishes', sink.published.some((s) => s.segment_id === 't:6:0'));
  await pipe.stop();
}

async function pipelineGmeet(): Promise<void> {
  console.log('pipeline: per-channel (gmeet) lane');
  const SR = 16000;
  const FRAME_MS = 200;
  const FRAME = new Float32Array((SR * FRAME_MS) / 1000).fill(0.05);
  const FAST = { minAudioDuration: 0.15, submitInterval: 0.1, confirmThreshold: 2, maxBufferDuration: 5, idleTimeoutSec: 2, sampleRate: SR };
  const gate = new PauseGate();
  gate.pause(Date.now() - 60_000);
  let calls = 0;
  const transcribe = async (): Promise<TranscriptionResult> => {
    calls++;
    return { text: 'hallo welt', language: 'de', duration: 1, segments: [{ start: 0, end: 1, text: 'hallo welt' }] };
  };
  const sink = captureSink();
  const pipe = createBotPipeline(baseInv({ platform: 'google_meet' }), sink, { transcribe, config: FAST, pauseGate: gate });
  await pipe.start();
  const t0 = Date.now();
  for (let i = 0; i < 12; i++) {
    pipe.feedAudio(0, 'Alice', FRAME, t0 + i * FRAME_MS);
    await sleep(60);
  }
  await pipe.stop();
  check('gmeet lane, paused: transcribe never called', calls === 0, String(calls));
  check('gmeet lane, paused: nothing published', sink.published.length === 0, JSON.stringify(sink.published));
}

// ── orchestrator ──
const recordingLifecycle = (): LifecycleSink & { readonly events: LifecycleEvent[] } => {
  const events: LifecycleEvent[] = [];
  return { events, async emit(e: LifecycleEvent) { events.push(e); } };
};

/** A join that waits in the lobby until the test admits it. */
const gatedJoin = () => {
  let admit: (() => void) | null = null;
  const driver: JoinDriver = {
    async join(report) {
      await report('awaiting_admission');
      await new Promise<void>((res) => { admit = res; });
      await report('active');
      return 'admitted' as JoinOutcome;
    },
    onRemoval() { return () => { /* */ }; },
    async leave() { /* */ },
    async withdraw() { /* */ },
  };
  return { driver, admit: () => admit?.() };
};

async function orchestratorPause(): Promise<void> {
  console.log('orchestrator');
  const gate = new PauseGate();
  const lifecycle = recordingLifecycle();
  let fire: ((a: Act) => void) | null = null;
  const { driver, admit } = gatedJoin();
  let gateAtStart: boolean | null = null;
  const pipeline: Pipeline = {
    async start() { gateAtStart = gate.allowsAudio(); },
    async stop() { /* */ },
  };
  const orch = createOrchestrator(baseInv(), {
    lifecycle, join: driver, pipeline, acts: noopActs((f) => { fire = f; }), aloneness: noopAloneness(), pauseGate: gate,
  });
  const run = orch.run();
  await sleep(10);
  check('lobby: bot is awaiting admission', lifecycle.events.at(-1)?.status === 'awaiting_admission');

  // The real wire shape from the meeting-api: unknown extra fields (meeting_id) ride along.
  const raw = parseAct({ action: 'pause', at: 1_700_000_000_000, meeting_id: 42 });
  check('parseAct narrows a pause act (extra fields ignored)', raw?.action === 'pause', JSON.stringify(raw));
  check('parseAct narrows a resume act', parseAct({ action: 'resume', meeting_id: 42 })?.action === 'resume');
  fire!(raw!);
  await sleep(10);
  check('pause act drives the gate (lobby)', gate.pausedSince === 1_700_000_000_000, String(gate.pausedSince));
  const ev = lifecycle.events.at(-1);
  check('pause confirmed over lifecycle.v1: aufnahme_pause.pausiert === true',
    ev?.aufnahme_pause?.pausiert === true && ev?.aufnahme_pause?.seit_ms === 1_700_000_000_000, JSON.stringify(ev));
  check('pause confirmation keeps the current status (lobby: awaiting_admission)', ev?.status === 'awaiting_admission', ev?.status);
  check('pause confirmation conforms to lifecycle.v1', validateLifecycle(ev), JSON.stringify(validateLifecycle.errors));

  admit();
  await sleep(20);
  check('lobby pause is already in effect when the pipeline starts', gateAtStart === false, String(gateAtStart));

  fire!({ action: 'resume' });
  await sleep(10);
  const ev2 = lifecycle.events.at(-1);
  check('resume act opens the gate', gate.allowsAudio());
  check('resume confirmed: aufnahme_pause = { pausiert:false, seit_ms:null } on status active',
    ev2?.aufnahme_pause?.pausiert === false && ev2?.aufnahme_pause?.seit_ms === null && ev2?.status === 'active', JSON.stringify(ev2));

  fire!({ action: 'leave' });
  const result = await run;
  check('run still ends normally (completed)', result.status === 'completed', result.status);
  check('every lifecycle event (incl. the pause confirmations) conforms to lifecycle.v1',
    lifecycle.events.every((e) => validateLifecycle(e)));
  check('the walk is still joining → awaiting_admission → active → completed',
    JSON.stringify([...new Set(lifecycle.events.map((e) => e.status))]) === JSON.stringify(['joining', 'awaiting_admission', 'active', 'completed']),
    JSON.stringify(lifecycle.events.map((e) => e.status)));

  // Without a wired gate the bot must NOT confirm a pause it cannot apply.
  const lc2 = recordingLifecycle();
  let fire2: ((a: Act) => void) | null = null;
  const { driver: d2 } = gatedJoin();
  createOrchestrator(baseInv(), {
    lifecycle: lc2, join: d2, pipeline, acts: noopActs((f) => { fire2 = f; }), aloneness: noopAloneness(),
  }).run();
  await sleep(10);
  const before = lc2.events.length;
  fire2!({ action: 'pause', at: 1 });
  await sleep(10);
  check('no gate wired: a pause act is never confirmed', lc2.events.length === before && !lc2.events.some((e) => e.aufnahme_pause));
}

// A suite that stalls on a never-settling promise lets node exit 0 with checks unrun — make that a failure.
let finished = false;
process.on('exit', (code) => {
  if (!finished && code === 0) {
    console.error('\n❌ pause-gate: suite ended before all checks ran');
    process.exitCode = 1;
  }
});

async function main(): Promise<void> {
  await gateUnit();
  await sinkUnit();
  await pipelineMixed();
  await pipelineGmeet();
  await orchestratorPause();
  finished = true;
  if (failed > 0) {
    console.error(`\n❌ pause-gate: ${failed} check(s) failed`);
    process.exit(1);
  }
  console.log('\n✅ pause-gate: gate, stt seam, transcript egress and acts/lifecycle wiring hold the pause.');
  process.exit(0);
}

main().catch((e) => { console.error(e); process.exit(1); });
