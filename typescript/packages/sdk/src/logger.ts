/**
 * Minimal logger interface for sync-engine modules (Block 5c).
 *
 * Python's `logging` module is everywhere in the sync engine port.
 * Node has no stdlib equivalent — we don't want to pull in `pino` or
 * `winston` for a single dependency in a library package. The contract
 * is intentionally small: four levels, structured args optional.
 *
 * Consumers can pass their own logger (`pino`, `winston`, `bunyan` —
 * all match this shape) or rely on the `consoleLogger` default. The
 * default uses `console.{debug,info,warn,error}` so output behaves
 * consistently across Node and edge runtimes.
 */

export interface Logger {
  debug(message: string, ...args: unknown[]): void;
  info(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
}

/**
 * Default console-backed logger. We intentionally use console methods
 * directly rather than wrapping — this avoids the indirection cost on
 * every log call and lets the user override console (e.g. via Sentry's
 * console capture) without further hooking.
 */
export const consoleLogger: Logger = {
  debug: (message, ...args) => console.debug(message, ...args),
  info: (message, ...args) => console.info(message, ...args),
  warn: (message, ...args) => console.warn(message, ...args),
  error: (message, ...args) => console.error(message, ...args),
};
