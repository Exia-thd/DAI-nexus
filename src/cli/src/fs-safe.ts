// Namespace import, not named: a named binding is fixed at module load and
// cannot be intercepted, which would leave the failure paths below untestable.
import fs from "node:fs";

/**
 * Filesystem operations that survive Windows' asynchronous release semantics.
 *
 * Windows refuses to rename onto — or remove — a path while any process still
 * holds it, and an indexer or virus scanner reading a file this process has
 * just written is enough. Three separate defects in this repository traced back
 * to that: a docs gate that removed its temp directory inside `finally` and so
 * reported a computed pass as a failure, a site build that renamed onto a
 * directory it had just deleted, and a state repository whose atomic write
 * reported failure for writes that had actually succeeded.
 *
 * The distinction these helpers draw is the one that matters: an operation
 * whose result the caller depends on must retry and then fail loudly, while an
 * operation that only tidies up must never be able to change what the caller
 * returns.
 */

const DEFAULT_DEADLINE_MS = 2_000;
const RETRY_PAUSE_MS = 25;

function pause(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/**
 * Rename `from` onto `to`, retrying while Windows still considers the
 * destination busy. Throws the last error if it never lands — a rename the
 * caller depends on must never be reported as done when it is not.
 */
export function renameWithRetry(
  from: string,
  to: string,
  deadlineMs: number = DEFAULT_DEADLINE_MS,
): void {
  const deadline = Date.now() + deadlineMs;
  for (;;) {
    try {
      fs.renameSync(from, to);
      return;
    } catch (error) {
      if (Date.now() >= deadline) throw error;
      pause(RETRY_PAUSE_MS);
    }
  }
}

/**
 * Remove a path for housekeeping. Never throws.
 *
 * Use only where failing to clean up must not change the caller's outcome —
 * inside a `finally`, or in a `catch` that is about to rethrow the real error.
 * Anywhere the removal itself is part of the contract, call `rmSync` directly
 * so a failure is visible.
 */
export function removeQuietly(target: string): void {
  try {
    fs.rmSync(target, {
      recursive: true,
      force: true,
      maxRetries: 10,
      retryDelay: 50,
    });
  } catch {
    // The OS reclaims its own temp space; the caller's result stands.
  }
}
