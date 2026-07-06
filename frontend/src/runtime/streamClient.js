/**
 * streamClient — SSE transport: manages one "merged subscription" lifecycle.
 *
 * Single responsibility: open/close an EventSource that drains a live event
 * stream from the backend. It is intentionally dumb about WHAT the events mean
 * (no parsing into messages, no storage, no mobx) — it just forwards raw event
 * objects to callbacks and lets the caller decide. Swapping SSE for websockets
 * later would only touch this file.
 *
 * Two subscription modes (mutually exclusive; pick one):
 *   - { scope: teamId }    → GET /stream?scope=teamId
 *                            The backend fans-in the whole team and DYNAMICALLY
 *                            expands members spawned mid-run, so the client
 *                            doesn't need to reconnect when agents appear.
 *   - { sessions: [ids] }  → GET /stream?sessions=id1,id2
 *                            Explicit set; drains all until each is done.
 *
 * Transport note: in dev we hit the backend directly (VITE_BACKEND_URL) because
 * Vite's http-proxy buffers SSE responses, collapsing the token stream into one
 * chunk. In prod the relative path is used (the deploy's reverse proxy must
 * forward SSE unbuffered).
 *
 * @module runtime/streamClient
 */

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

export class StreamClient {
  /**
   * Subscribe to a live event stream.
   *
   * @param {{scope?: string, sessions?: string[]}} opts — one of the two modes
   * @param {{onEvent?: (e: object) => void, onDone?: () => void, onError?: (e: unknown) => void}} cb
   * @returns {{ dispose(): void }} handle — call dispose() to close the stream
   */
  subscribe(opts, cb) {
    const url = this._buildUrl(opts);
    const es = new EventSource(url);
    es.onmessage = (ev) => {
      if (ev.data === "[DONE]") {
        console.log("[SSE] [DONE]");
        cb.onDone?.();
        return;
      }
      try {
        const evt = JSON.parse(ev.data);
        console.log("[SSE]", evt.kind, evt.session_id?.slice(0, 8), evt.speaker || "", evt.delta?.slice(0, 20) || evt.tool || "");
        cb.onEvent?.(evt);
      } catch {
        /* ignore malformed frames */
      }
    };
    es.onerror = (e) => {
      // EventSource auto-reconnects by default after the server closes a run's
      // response; that reconnect is EXPECTED (it's how we wait for the next
      // run). Only surface genuinely unexpected errors.
      cb.onError?.(e);
    };
    return {
      dispose() {
        es.close();
      },
    };
  }

  /** Build the SSE URL for the chosen subscription mode. */
  _buildUrl(opts) {
    if (opts.scope) {
      return `${BACKEND}/stream?scope=${encodeURIComponent(opts.scope)}`;
    }
    if (opts.sessions && opts.sessions.length) {
      const ids = opts.sessions.map(encodeURIComponent).join(",");
      return `${BACKEND}/stream?sessions=${ids}`;
    }
    // nothing to subscribe to — return a URL that yields immediate [DONE]
    return `${BACKEND}/stream`;
  }
}
