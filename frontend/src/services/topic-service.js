/**
 * Topic service — the ONLY place that talks to the /topics backend.
 * Views go through topic-store actions → these functions. Never call directly.
 */

/** List all topics (newest first), with latest session info merged in. */
export async function listTopics() {
    const res = await fetch("/topics");
    if (!res.ok) throw new Error(`listTopics: ${res.status}`);
    return res.json();
}
