/**
 * sales-claw pause patch — the recording PAUSE GATE (acts.v1 `pause` / `resume`).
 *
 * Added on top of @vexa/bot from vexaai/vexa-lite:v0.12.28 (Apache-2.0). The bot stays seated in
 * the meeting; while paused nothing of the room may become text (DSGVO — "im Zweifel lieber weg"):
 *   • the pause begins at the CLICK time carried by the act (`at`, epoch ms), not at its arrival;
 *   • while paused the stt port is never called and the lane is fed silence (`gateTranscribe`,
 *     `gateBotPipeline`) — buffered, untranscribed audio is thereby discarded;
 *   • every segment whose start lies in a pause window [at, resume) is dropped at the transcript
 *     egress, even when its STT call started before the pause or it surfaces after the resume;
 *   • segments already published with start ≥ at (between the click and the act's arrival) are
 *     retracted when the pause takes effect (`gateTranscriptSink`).
 * One gate instance is shared by the orchestrator (acts → gate → lifecycle confirmation) and the
 * pipeline; it is built at the composition root BEFORE the join, so a pause sent from the lobby is
 * already in effect when the pipeline starts.
 */
import type { TranscriptionResult } from '@vexa/transcribe-whisper';
import type { BotPipeline, Transcribe } from './pipeline.js';
import type { TranscriptSink } from './ports.js';

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

  /** May a segment starting at `startEpochS` (epoch SECONDS, the transcript.v1 timing) be kept? */
  allowsSegment(startEpochS: number): boolean {
    const ms = startEpochS * 1000;
    if (!Number.isFinite(ms)) return this.since === null && this.windows.length === 0;
    if (this.since !== null && ms >= this.since) return false;
    return !this.windows.some((w) => ms >= w.from && ms < w.to);
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
 *  ones are removed server-side by the meeting-api's deletion of segments with start ≥ at. */
export const RETRACT_WINDOW_MS = 30_000;

/** The transcript egress: drop every segment inside a pause window; on pause, retract the ids
 *  published in the last RETRACT_WINDOW_MS whose start is at/after the click. */
export function gateTranscriptSink(
  sink: TranscriptSink,
  gate: PauseGate,
  opts: { now?: () => number; windowMs?: number } = {},
): TranscriptSink {
  const now = opts.now ?? Date.now;
  const windowMs = opts.windowMs ?? RETRACT_WINDOW_MS;
  const recent = new Map<string, { startS: number; publishedMs: number }>();
  const prune = (): void => {
    const floor = now() - windowMs;
    for (const [id, r] of recent) if (r.publishedMs < floor) recent.delete(id);
  };
  gate.onPause((atMs) => {
    prune();
    const ids: string[] = [];
    for (const [id, r] of recent) if (!(r.startS * 1000 < atMs)) ids.push(id);
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
      if (!gate.allowsSegment(segment.start)) return;
      prune();
      recent.set(segment.segment_id, { startS: segment.start, publishedMs: now() });
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
