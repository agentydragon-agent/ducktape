/**
 * What `VirtualizedHistory` marks for inspection, for tests and for chasing a reader-position
 * bug: User Timing marks for its scroll and layout decisions, and whether its layout has come
 * to rest. The Playwright harness installs the test-only mark collector before the app loads.
 */

/** Why the history started or stopped following the tail. */
export type FollowReason =
  | "jump-to-latest"
  | "returned-to-previous-bottom"
  | "scrolled-to-bottom"
  | "scrolled-up"
  | "wheel-up"
  | "key-up"
  | "touch-up"
  | "disclosure-click";

/** Mirrored by the typed events in agentplane/app/testing/thread_view_marks.py. */
export type ThreadViewEvent =
  | { kind: "follow"; following: boolean; reason: FollowReason }
  | { kind: "scroll"; scrollTop: number; scrollHeight: number; followed: boolean }
  | { kind: "scrollend"; restoring: boolean; capturing: boolean }
  /** The history's content or tail changed size. `pinned`: it was followed to the bottom. */
  | { kind: "resize"; scrollTop: number; scrollHeight: number; pinned: boolean }
  | { kind: "click"; scrollTop: number; scrollHeight: number; clientHeight: number }
  | { kind: "anchor"; key: string; offset: number }
  | { kind: "restore"; key: string; correction: number | null }
  | { kind: "prepend"; added: number }
  | { kind: "load-older" }
  /** A row's height was read. `estimate` is what the virtualizer laid it out with before: a
   * remembered reading of an earlier visit if `remembered`, else a flat guess. */
  | { kind: "measure"; key: string; estimate: number; measured: number; first: boolean; remembered: boolean }
  | { kind: "settled"; settled: boolean };

declare global {
  interface Window {
    /** Set by the Playwright init script before the app loads, not by production code. */
    __agentplaneThreadViewMarksEnabled?: boolean;
  }
}

/** Emits browser User Timing marks only when the test harness enables them. */
export function markThreadViewEvent(event: ThreadViewEvent): void {
  if (!window.__agentplaneThreadViewMarksEnabled) return;
  performance.mark(`agentplane:thread-view:${event.kind}`, { detail: event });
}

/** A layout counts as at rest once this many frames pass without it changing. */
const QUIET_FRAMES = 5;

/**
 * Whether a layout has come to rest. `changed()` says it moved; it is unsettled until it has
 * stayed put for `QUIET_FRAMES` frames, and while `busy()` says something that will move it is still
 * under way: a correction, or content a row is waiting for.
 */
export class LayoutSettle {
  readonly #busy: () => boolean;
  readonly #onChange: (settled: boolean) => void;
  #settled = false;
  #frame: number | null = null;

  constructor(busy: () => boolean, onChange: (settled: boolean) => void) {
    this.#busy = busy;
    this.#onChange = onChange;
    this.#wait(0);
  }

  changed(): void {
    if (this.#settled) {
      this.#settled = false;
      this.#onChange(false);
    }
    if (this.#frame !== null) cancelAnimationFrame(this.#frame);
    this.#wait(0);
  }

  dispose(): void {
    if (this.#frame !== null) cancelAnimationFrame(this.#frame);
    this.#frame = null;
  }

  #wait(quiet: number): void {
    this.#frame = requestAnimationFrame(() => {
      if (this.#busy()) return this.#wait(0);
      if (quiet + 1 < QUIET_FRAMES) return this.#wait(quiet + 1);
      this.#frame = null;
      this.#settled = true;
      this.#onChange(true);
    });
  }
}
