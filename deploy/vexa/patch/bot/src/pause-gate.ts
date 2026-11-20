/**
 * sales-claw pause patch — the recording PAUSE GATE (acts.v1 `pause` / `resume`).
 *
 * Added on top of @vexa/bot from vexaai/vexa-lite:v0.12.28 (Apache-2.0). The bot stays seated in
 * the meeting; while paused nothing of the room may become text (DSGVO — "im Zweifel lieber weg"):
 *   • the pause begins at the CLICK time carried by the act (`at`, epoch ms), not at its arrival;
 *   • while paused the stt port is never called and the lane is fed silence (`gateTranscribe`,
 *     `gateBotPipeline`) — buffered, untranscribed audio is thereby discarded;
 *   • every segment that touches a pause window [at, resume) — starts inside it, or starts before
 *     and ends after its start (ruling R4: "ganzen Satz loeschen") — is dropped at the transcript
 *     egress, even when its STT call started before the pause or it surfaces after the resume;
 *   • segments already published with start ≥ at or end > at (between the click and the act's
 *     arrival) are retracted when the pause takes effect (`gateTranscriptSink`);
 *   • the capture-signal tape (O-TEL-1, teed before the feed) gets silence and no captions while
 *     paused (`gateCaptureSignalSink`).
 * One gate instance is shared by the orchestrator (acts → gate → lifecycle confirmation) and the
 * pipeline; it is built at the composition root BEFORE the join, so a pause sent from the lobby is
 * already in effect when the pipeline starts.
 */
import type { TranscriptionResult } from '@vexa/transcribe-whisper';
import type { BotPipeline, Transcribe } from './pipeline.js';
import type { CapturedFrame, TelemetrySink, TranscriptSink } from './ports.js';

export class PauseGate {
  private since: number | null = null;
  /** Closed pause windows [from, to) in epoch ms. Kept for the whole meeting: a late result for a
   *  paused stretch must stay dropped after the resume. */
  private readonly windows: Array<{ from: number; to: number }> = [];
  private readonly listeners = new Set<(atMs: number) => void>();

  constructor(private readonly now: () => number = Date.now) {}

  /** Pause from the click time `atMs`. A second pause keeps the first click time. A missing or
   *  future click time (clock skew) is clamped to now — the pause never starts later than now. */
  pause(atMs: number): void {
    if (this.since !== null) return;
    const t = this.now();
    const at = Number.isFinite(atMs) ? Math.min(atMs, t) : t;
    this.since = at;
    for (const listener of this.listeners) {
      try { listener(at); } catch { /* a listener fault must never undo the pause */ }
    }
  }

  /** End the pause now. The closed window [at, now) stays forbidden. No-op when not paused. */
  resume(): void {
    if (this.since === null) return;
    this.windows.push({ from: this.since, to: Math.max(this.since, this.now()) });
    this.since = null;
  }

  /** The click time of the running pause (epoch ms), or null when recording. */
  get pausedSince(): number | null {
    return this.since;
  }

  allowsAudio(): boolean {
    return this.since === null;
  }

  /** May a segment [startEpochS, endEpochS] (epoch SECONDS, the transcript.v1 timing) be kept?
   *  Ruling R4 ("lieber weg / ganzen Satz loeschen"): NO if it touches any pause window at all —
   *  it starts inside one, or starts before and ends after the window's start. A segment ending
   *  exactly at the click is kept. Without `endEpochS` the segment is treated as a point. */
  allowsSegment(startEpochS: number, endEpochS?: number): boolean {
    const start = startEpochS * 1000;
    if (!Number.isFinite(start)) return this.since === null && this.windows.length === 0;
    const endRaw = endEpochS === undefined ? start : endEpochS * 1000;
    const end = Number.isFinite(endRaw) ? Math.max(start, endRaw) : start;
    const touches = (from: number, to: number): boolean => start < to && (start >= from || end > from);
    if (this.since !== null && touches(this.since, Number.POSITIVE_INFINITY)) return false;
    return !this.windows.some((w) => touches(w.from, w.to));
  }

  /** Called with the click time whenever a pause takes effect. Returns an unsubscribe fn. */
  onPause(listener: (atMs: number) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }
}

/** The stt seam: while paused, no call — an empty result, the same shape the bot already uses for
 *  transcribe-disabled meetings, so every lane treats the window as silence. */
export function gateTranscribe(transcribe: Transcribe, gate: PauseGate, language?: string | null): Transcribe {
  return async (pcm, prompt): Promise<TranscriptionResult> => {
    if (!gate.allowsAudio()) return { text: '', language: language ?? 'en', duration: 0, segments: [] };
    return transcribe(pcm, prompt);
  };
}

/** How long published segment ids are remembered for the retraction on pause (plan: 30 s). Older
 *  ones are removed server-side by the meeting-api (Task 2: start ≥ at, and under R4 end > at). */
export const RETRACT_WINDOW_MS = 30_000;

/** The transcript egress: drop every segment touching a pause window (R4); on pause, retract the ids
 *  published in the last RETRACT_WINDOW_MS that start at/after the click or end after it (R4). */
export function gateTranscriptSink(
  sink: TranscriptSink,
  gate: PauseGate,
  opts: { now?: () => number; windowMs?: number } = {},
): TranscriptSink {
  const now = opts.now ?? Date.now;
  const windowMs = opts.windowMs ?? RETRACT_WINDOW_MS;
  const recent = new Map<string, { startS: number; endS: number; publishedMs: number }>();
  const prune = (): void => {
    const floor = now() - windowMs;
    for (const [id, r] of recent) if (r.publishedMs < floor) recent.delete(id);
  };
  gate.onPause((atMs) => {
    prune();
    const ids: string[] = [];
    // R4: start ≥ at, or straddling the click (end > at) — the whole sentence goes.
    for (const [id, r] of recent) if (!(r.startS * 1000 < atMs) || r.endS * 1000 > atMs) ids.push(id);
    for (const id of ids) recent.delete(id);
    if (ids.length === 0) return;
    if (!sink.retract) {
      console.error(`[bot] pause: ${ids.length} segment(s) after the click cannot be retracted (sink has no retract)`);
      return;
    }
    void sink.retract(ids).catch((e) => console.error(`[bot] pause: retract rejected: ${String(e)}`));
  });
  return {
    async publish(segment) {
      if (!gate.allowsSegment(segment.start, segment.end)) return;
      prune();
      recent.set(segment.segment_id, { startS: segment.start, endS: segment.end, publishedMs: now() });
      await sink.publish(segment);
    },
    ...(sink.retract
      ? {
          async retract(segmentIds: string[]) {
            for (const id of segmentIds) recent.delete(id);
            await sink.retract!(segmentIds);
          },
        }
      : {}),
  };
}

/** The audio feed: while paused (or for a frame stamped inside a pause window) the lane gets
 *  silence of the same length — its turn/ring clocks keep running, but no captured sound is held
 *  in its buffers or can reach STT after the resume. */
export function gateBotPipeline(pipeline: BotPipeline, gate: PauseGate): BotPipeline {
  const blocked = (tsMs: number): boolean => !gate.allowsAudio() || !gate.allowsSegment(tsMs / 1000);
  return {
    ...pipeline,
    feedAudio: (channel, glowName, pcm, tsMs) =>
      pipeline.feedAudio(channel, glowName, blocked(tsMs) ? new Float32Array(pcm.length) : pcm, tsMs),
    feedMixedAudio: (pcm, tsMs) =>
      pipeline.feedMixedAudio(blocked(tsMs) ? new Float32Array(pcm.length) : pcm, tsMs),
  };
}

/** Final-Review I4 — the O-TEL-1 capture-signal tap (`signalRecorder.sink`) is teed by the capture
 *  bridge BEFORE the pipeline feed, so the feed gate above never sees it; if capture-signal is ever
 *  switched on, the raw room audio of a pause would be persisted and uploaded. Gate it the same way:
 *  while paused (or for a frame stamped inside a pause window) the tape gets silence of the same
 *  length (seq/clock intact, no sound), and caption text (Teams CC) is dropped. Hints, CSRC and
 *  observations carry no speech and pass through unchanged (prototype delegation). */
export function gateCaptureSignalSink<S extends TelemetrySink>(sink: S, gate: PauseGate): S {
  const blocked = (tsMs: number): boolean => !gate.allowsAudio() || !gate.allowsSegment(tsMs / 1000);
  const gated = Object.create(sink) as S;
  (gated as TelemetrySink).captureFrame = (frame: CapturedFrame): void => {
    if (!blocked(frame.ts)) { sink.captureFrame(frame); return; }
    const samples = Number.isFinite(frame.pcm_len) && frame.pcm_len > 0 ? frame.pcm_len : 0;
    sink.captureFrame({ ...frame, pcm: Buffer.alloc(samples * 4).toString('base64'), rms: 0 });
  };
  const caption = (sink as { captureCaption?: (c: unknown) => void }).captureCaption;
  if (typeof caption === 'function') {
    (gated as { captureCaption?: (c: unknown) => void }).captureCaption = (c: unknown): void => {
      if (gate.allowsAudio()) caption.call(sink, c);
    };
  }
  return gated;
}
