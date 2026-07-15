/**
 * Stream service: the unified SSE client for the new event schema.
 *
 * Two transport modes:
 *   - sendMessage (POST /sessions/:id/messages): fetch + ReadableStream, because
 *     it's a POST that returns the agent's run inline. Used for user→agent sends.
 *   - subscribe (GET /sessions/:id/stream?scope=): EventSource, for passively
 *     watching a running session (or a whole team via scope fan-in).
 *
 * Both decode the SAME event schema (see backend event_schema.py). Each frame is
 * a `data: {json}\n\n` line; events carry session_id + speaker so a fanned-in
 * stream is self-attributing.
 *
 * STREAMING NOTE: in dev, Vite's http-proxy buffers SSE responses, which
 * collapses the token stream into one big chunk (the fetch reader gets a
 * single read instead of per-token reads). To keep token-by-token streaming we
 * talk to the backend directly in dev (VITE_BACKEND_URL); in prod we use the
 * relative path (served by the same origin / a proper reverse proxy that
 * forwards SSE unbuffered).
 */

// Dev: hit the backend directly so SSE isn't buffered by Vite's proxy.
// Prod: relative path — the deploy's reverse proxy must forward SSE unbuffered.
const BACKEND = import.meta.env.VITE_BACKEND_URL || "";

/**
 * Send a user message and stream the agent's run back.
 *
 * @param {object} opts
 * @param {string} opts.sessionId
 * @param {string} opts.content
 * @param {AbortSignal} [opts.signal]
 * @param {(evt: object) => void} [opts.onEvent]
 * @param {() => void} [opts.onDone]
 * @param {(err: Error) => void} [opts.onError]
 */
export async function sendMessage({
    sessionId,
    content,
    signal,
    onEvent,
    onDone,
    onError,
}) {
    let res;
    try {
        res = await fetch(
            `${BACKEND}/sessions/${encodeURIComponent(sessionId)}/messages`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Accept: "text/event-stream",
                },
                body: JSON.stringify({ content }),
                signal,
            }
        );
    } catch (e) {
        if (e.name === "AbortError") return;
        onError?.(e);
        return;
    }

    if (!res.ok || !res.body) {
        if (typeof window !== "undefined")
            window.__ssErr = `status ${res.status}`;
        onError?.(new Error(`send failed: ${res.status}`));
        return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let readCount = 0;
    try {
        if (typeof window !== "undefined") window.__ssStarted = true;
        for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            readCount++;
            if (typeof window !== "undefined") window.__ssReads = readCount;
            buf += decoder.decode(value, { stream: true });
            let sep;
            while ((sep = buf.indexOf("\n\n")) >= 0) {
                const frame = buf.slice(0, sep);
                buf = buf.slice(sep + 2);
                const evt = parseFrame(frame);
                if (evt) onEvent?.(evt);
            }
        }
        onDone?.();
    } catch (e) {
        if (typeof window !== "undefined") window.__ssErr = String(e);
        if (e.name === "AbortError") return;
        onError?.(e);
    }
}

/**
 * Passively subscribe to a session's live stream (EventSource).
 * Pass `scopeId` to fan-in a whole team's participants into one stream.
 *
 * @param {string} sessionId
 * @param {{ scopeId?: string, onEvent?: (e: object) => void, onDone?: () => void, onError?: (e: unknown) => void }} [opts]
 * @returns {{ es: EventSource, dispose: () => void }}
 */
export function subscribe(
    sessionId,
    { scopeId, onEvent, onDone, onError } = {}
) {
    const url = scopeId
        ? `${BACKEND}/sessions/${encodeURIComponent(sessionId)}/stream?scope=${encodeURIComponent(scopeId)}`
        : `${BACKEND}/sessions/${encodeURIComponent(sessionId)}/stream`;
    const es = new EventSource(url);
    es.onmessage = (ev) => {
        if (ev.data === "[DONE]") {
            onDone?.();
            es.close();
            return;
        }
        try {
            onEvent?.(JSON.parse(ev.data));
        } catch {
            /* ignore malformed */
        }
    };
    es.onerror = (e) => onError?.(e);
    return { es, dispose: () => es.close() };
}

/** Pull the first `data:` line out of an SSE frame and JSON-parse it. */
function parseFrame(frame) {
    const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
    if (!dataLine) return null;
    const payload = dataLine.slice(5).trim();
    if (!payload || payload === "[DONE]") return null;
    try {
        return JSON.parse(payload);
    } catch {
        return null;
    }
}
