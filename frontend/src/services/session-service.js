/**
 * Service layer: the ONLY place that talks to backends.
 * Views go through store actions -> these functions. Never call directly.
 */

/** Create a new session (conversation container). */
export async function createSession({ title, kind = "root", topic_id = "main" } = {}) {
    const res = await fetch("/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, title, topic_id }),
    });
    if (!res.ok) throw new Error(`createSession: ${res.status}`);
    return res.json();
}

/** List all sessions (most recently updated first). */
export async function listSessions() {
    const res = await fetch("/sessions");
    if (!res.ok) throw new Error(`listSessions: ${res.status}`);
    return res.json();
}

/** Get one session's metadata + history. */
export async function getSession(id) {
    const res = await fetch(`/sessions/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error(`getSession: ${res.status}`);
    return res.json();
}

/** Update a session's title / status. */
export async function updateSession(id, { title, status } = {}) {
    const res = await fetch(`/sessions/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, status }),
    });
    if (!res.ok) throw new Error(`updateSession: ${res.status}`);
    return res.json();
}

/**
 * Set the session's last-message preview (shown as the 2nd line in the list).
 * Merged into metadata server-side (existing metadata preserved).
 */
export async function setPreview(id, preview, speaker) {
    const res = await fetch(`/sessions/${encodeURIComponent(id)}/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preview, speaker }),
    });
    if (!res.ok) throw new Error(`setPreview: ${res.status}`);
    return res.json();
}

/**
 * Reset a session's conversation history (clear its checkpointer thread).
 * The session row stays — only its message history is wiped. Used by the
 * default entry's "new chat".
 */
export async function resetHistory(id) {
    const res = await fetch(`/sessions/${encodeURIComponent(id)}/reset`, {
        method: "POST",
    });
    if (!res.ok) throw new Error(`resetHistory: ${res.status}`);
    return res.json();
}

/** Delete a session. */
export async function deleteSession(id) {
    const res = await fetch(`/sessions/${encodeURIComponent(id)}`, {
        method: "DELETE",
    });
    if (!res.ok) throw new Error(`deleteSession: ${res.status}`);
    return res.json();
}
