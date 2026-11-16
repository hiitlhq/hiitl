/**
 * The active OpenTelemetry trace, read for the envelope's `trace_id`.
 *
 * envelope_schema.json: `trace_id` is "Auto-propagated from execution context". The SDK reads the active span's trace
 * id through the OpenTelemetry API when the application has installed it (`@opentelemetry/api`); the API is never a
 * dependency of this package. It is resolved once, at load. The API keeps its registry on the global object, so this
 * copy sees the context manager and spans the application registered. Without it, or outside a span, there is no
 * trace id. Mirrors python/hiitl/sdk/trace_context.py.
 */

import { createRequire } from 'node:module';

interface SpanContext {
  traceId: string;
}

interface OpenTelemetryApi {
  context: { active(): unknown };
  trace: { getSpanContext(context: unknown): SpanContext | undefined };
  isSpanContextValid(spanContext: SpanContext): boolean;
}

const api: OpenTelemetryApi | undefined = (() => {
  try {
    return createRequire(import.meta.url)('@opentelemetry/api') as OpenTelemetryApi;
  } catch {
    return undefined; // the API is not installed: there is no span to read
  }
})();

/**
 * The active span's trace id as W3C Trace Context writes it (32 lowercase hex), or undefined.
 *
 * Only a valid span context counts: a span from the API's no-op tracer (the API installed with no SDK) carries the
 * all-zero id, which names no trace.
 */
export function activeTraceId(): string | undefined {
  if (api === undefined) return undefined;
  const spanContext = api.trace.getSpanContext(api.context.active());
  return spanContext !== undefined && api.isSpanContextValid(spanContext) ? spanContext.traceId : undefined;
}
