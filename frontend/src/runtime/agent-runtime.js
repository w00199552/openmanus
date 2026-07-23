/**
 * agentRuntime — the facade: orchestrates store + client + reducer, exposes
 * observable state and actions. This is the ONLY object the view layer touches.
 *
 * Responsibilities (pure orchestration — it owns no domain logic itself):
 *   - track which topic is currently being observed (the backend keys runs by
 *     topic_id — POST /topics/{topic_id}/messages)
 *   - on switch: (re)build the SSE subscription, drain events into the topic's
 *     message bucket
 *   - on send: POST to trigger the run (background), optimistic user bubble,
 *     ensure a subscription is receiving the output
 *   - route each incoming event into the active topic's bucket (events still
 *     carry a real session_id, but we don't use it as a store key — the user
 *     looks at a topic view, not a session view)
 *   - keep running-state + the topic list (unread/preview) in sync
 *
 * It deliberately does NOT: transform events (→ eventReducer), talk to
 * EventSource directly (→ streamClient), or hold message arrays itself
 * (→ messageStore). Each concern is one file; this one wires them.
 *
 * @module runtime/agentRuntime
 */

import { makeAutoObservable, runInAction } from "mobx";

import { MessageStore } from "./message-store.js";
import { StreamClient } from "./stream-client.js";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

export class AgentRuntime {
    /** @type {MessageStore} */
    messageStore = new MessageStore();
    /** @type {StreamClient} */
    streamClient = new StreamClient();

    // ─── injected collaborators ──────────────────────────────────────────────
    /** @type {null | { topics: any[], activeTopicId: string|null, active: any, bumpActivity: Function, markRunning: Function, markStatus: Function, load: Function, select: Function }} */
    _topicStore = null;
    /** @type {null | SandboxStore} injected post-construction for cd delegation */
    _sandboxStore = null;

    // ─── internal handles (NOT observable — prefixed _) ─────────────────────
    _subHandle = null; // current SSE subscription handle
    _sendAborts = {}; // topicId → AbortController (for stop)
    _preSendTopicIds = null; // topic id snapshot before a main-topic turn (for _afterDelegation diff)
    // NOTE: With the topic-id send path, the messageStore is keyed by topicId.
    // SSE events still carry a real session_id, but we route them to the active
    // topic's bucket (see _dispatchEvent) so all messages fan-in under one view.

    // ─── observable state ───────────────────────────────────────────────────
    /** The topic the user is currently observing. session_id comes from SSE. */
    activeTopicId = null;
    /** topicId → bool: a run is currently streaming for that topic. */
    runningBySession = {};
    /** last error message, if any. */
    error = null;

    constructor() {
        makeAutoObservable(this);
        if (typeof window !== "undefined") window.__rt = this; // DEBUG
    }

    /** Inject the TopicStore (for list unread/preview/status sync). Optional. */
    setTopicStore(s) {
        this._topicStore = s;
    }

    /** Inject the SandboxStore (for cd command delegation + workdir sync). Optional. */
    setSandboxStore(sb) {
        this._sandboxStore = sb;
    }

    // ─── observable views (computed) ─────────────────────────────────────────

    /** Messages for the current topic (keyed by topicId in the store). */
    get activeMessages() {
        return this.messageStore.get(this.activeTopicId);
    }

    /** Is the current topic's run actively streaming? */
    get isRunning() {
        return !!this.runningBySession[this.activeTopicId];
    }

    // ─── actions ─────────────────────────────────────────────────────────────

    /**
     * Switch the topic the user is observing. The backend keys runs by topic_id
     * now (POST /topics/{topic_id}/messages), so the runtime no longer tracks a
     * separate session_id at the top level — the real session_id arrives in
     * each SSE event and is folded into the active topic's message bucket.
     * @param {string} topicId  the topic to focus
     */
    setActive(topicId) {
        this.activeTopicId = topicId;
        // Sync sandbox workdir to match the selected topic
        this._sandboxStore?.syncFromTopic();
        // Rebuild the live subscription for the new view.
        this._resubscribe();
    }

    /**
     * User sends a message to a topic: trigger the agent run (background POST
     * to /topics/{topic_id}/messages), optimistically show the user bubble, and
     * ensure we're subscribed to receive the output.
     */
    async send(topicId, text) {
        if (!text || !text.trim()) return;

        // ── cd command: delegate to SandboxStore (doesn't trigger agent) ───
        const trimmed = text.trim();
        const lower = trimmed.toLowerCase();
        if (lower === "cd" || lower.startsWith("cd ")) {
            const path = trimmed.slice(2).trim(); // everything after "cd"
            await this._handleCd(topicId, path, text);
            return;
        }

        // Snapshot topic ids BEFORE the turn — used by _afterDelegation to detect
        // NEW topics created during this turn (dispatch may create team/subagent
        // topics, and the topic list may get reloaded mid-turn, so we can't
        // diff against the live list at _endRun time).
        this._preSendTopicIds = new Set(
            (this._topicStore?.topics || []).map((t) => t.id)
        );

        // 1. optimistic user bubble (keyed by topicId in the message store)
        this.messageStore.appendMessage(topicId, {
            id: `u-${Date.now()}`,
            role: "user",
            speaker: "user",
            content: [{ type: "text", text }],
            status: "complete",
            createdAt: Date.now(),
        });

        runInAction(() => {
            this.runningBySession[topicId] = true;
            this.error = null;
        });
        // mark the active topic running (the topic is what the list surfaces
        // to the user).
        if (topicId) this._topicStore?.markRunning?.(topicId);

        // 2. Rebuild the subscription BEFORE triggering the run. The server starts
        //    the run the instant POST is received (async), so events can appear the
        //    moment POST returns. If we re-subscribe AFTER POST (as we once did),
        //    early events are lost to the old (already-done) drain / a reconnecting
        //    EventSource. Building the drain first guarantees every event is caught.
        if (this.activeTopicId === topicId) {
            // Rebuild the subscription WITHOUT reloading history: the topic's
            // messages are already in the store (incl. the optimistic user bubble
            // just appended), and a history fetch would overwrite that bubble.
            this._resubscribe({ loadHistory: false });
        } else {
            this.streamClient.subscribe(
                { topic: topicId },
                {
                    onEvent: (e) => this._dispatchEvent(e),
                }
            );
        }

        // 3. POST to trigger the run (does NOT stream back — events arrive via the
        //    subscription built above). AbortController lets stop() cancel it.
        const ac = new AbortController();
        this._sendAborts[topicId] = ac;
        try {
            const res = await fetch(
                `${BACKEND}/topics/${encodeURIComponent(topicId)}/messages`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ content: text }),
                    signal: ac.signal,
                }
            );
            if (!res.ok) throw new Error(`send failed: ${res.status}`);
        } catch (e) {
            if (e.name === "AbortError") return; // user pressed stop
            runInAction(() => (this.error = e.message || String(e)));
            this._endRun(topicId);
            return;
        } finally {
            delete this._sendAborts[topicId];
        }
    }

    /**
     * Handle a cd command: show user bubble, delegate API call to SandboxStore,
     * then display the system reply. All workdir state is owned by SandboxStore.
     * @param {string} topicId  the active topic (used as the messageStore key)
     */
    async _handleCd(topicId, path, originalText) {
        // optimistic user bubble
        this.messageStore.appendMessage(topicId, {
            id: `u-${Date.now()}`,
            role: "user",
            speaker: "user",
            content: [{ type: "text", text: originalText }],
            status: "complete",
            createdAt: Date.now(),
        });

        // SandboxStore.cd still talks to /sessions/{session_id}/cd — resolve the
        // topic's latest session id. If we can't, fall back to the topic id; the
        // backend tolerates a missing path and the only consequence is no workdir
        // switch, surfaced as a system error bubble.
        const sessionId = this._topicStore?.active?.session_id || topicId;
        try {
            const body = await this._sandboxStore.cd(sessionId, path);
            const reply =
                body.action === "pwd"
                    ? `📁 Current workdir: ${body.workdir}`
                    : `📁 Workdir switched to: ${body.workdir}`;
            this.messageStore.appendMessage(topicId, {
                id: `cd-${Date.now()}`,
                role: "assistant",
                speaker: "system",
                content: [{ type: "text", text: reply }],
                status: "complete",
                createdAt: Date.now(),
            });
        } catch (e) {
            this.messageStore.appendMessage(topicId, {
                id: `cd-err-${Date.now()}`,
                role: "assistant",
                speaker: "system",
                content: [{ type: "text", text: `❌ ${e.message}` }],
                status: "complete",
                createdAt: Date.now(),
            });
        }
    }

    /** Stop an in-flight run for a topic (aborts the POST + clears running). */
    stop(topicId = this.activeTopicId) {
        const ac = this._sendAborts[topicId];
        if (ac) ac.abort();
        this._endRun(topicId);
    }

    /** Clear a topic's messages (e.g. on "new chat" reset). */
    clear(topicId) {
        this.messageStore.clear(topicId);
    }

    // ─── internals ───────────────────────────────────────────────────────────

    /**
     * Route one incoming event into the active topic's message bucket + update
     * running state. Called by the streamClient subscription callback.
     *
     * The backend's event still carries a real `session_id`, but with the
     * topic-keyed send path the view aggregates messages per topic. We therefore
     * apply each event to `this.activeTopicId` (the topic the user is observing),
     * so fan-in / sub-agent messages all land in one bucket. `session_id` is
     * intentionally not used as a store key at this layer.
     */
    _dispatchEvent(event) {
        runInAction(() => {
            const topicId = this.activeTopicId;
            if (topicId) this.messageStore.applyEvent(topicId, event);
            // done → the topic's run finished
            if (event.kind === "done" && topicId) {
                this._endRun(topicId);
            }
            if (event.kind === "error") {
                this.error = event.message || "agent error";
            }
        });
    }

    /** Mark a topic's run as finished + sync the topic list. */
    _endRun(topicId) {
        runInAction(() => {
            this.runningBySession[topicId] = false;
        });
        // Attribute activity to the topic the user is currently looking at.
        const activeTopicId = this._topicStore?.activeTopicId;
        if (activeTopicId) {
            const preview = this._lastAssistantText(topicId);
            const isActive = this.activeTopicId === topicId;
            this._topicStore.bumpActivity?.(activeTopicId, {
                unread: isActive ? 0 : 1,
                preview,
                speaker: "assistant",
            });
            this._topicStore.markStatus?.(activeTopicId, "active");
        }
        // When the main topic's turn ends, the agent may have dispatched a new
        // sub-agent / team (via the dispatch tool). Refresh the topic list so the
        // new child appears without a manual page reload, then auto-switch to it
        // so the user lands on the delegated work.
        if (topicId === "manus" || topicId === "main") {
            this._afterDelegation().catch(() => {});
        }
    }

    /**
     * After a main-topic turn: reload the topic list and, if a NEW derived
     * topic (team / top-level subagent) appeared, switch the view to it.
     * Detects "new" by diffing the id set before vs after the reload — more
     * reliable than trusting a parent field.
     */
    async _afterDelegation() {
        if (!this._topicStore) return;
        // Use the snapshot taken at send() time — NOT the live list (which may
        // have been reloaded mid-turn, already containing the new topics).
        const before = this._preSendTopicIds || new Set();
        this._preSendTopicIds = null;
        const list = await this._topicStore.load();
        const child = _newestDerived(list, before);
        if (child) {
            // child is a topic — observe it by its topic_id. The real session_id
            // will arrive in subsequent SSE events and is folded into the topic's
            // message bucket; we no longer need it at the top level.
            this.setActive(child.id);
            this._topicStore.select(child.id);
        }
    }

    /**
     * Rebuild the live SSE subscription for the active topic.
     * @param {{ loadHistory?: boolean }} opts — loadHistory defaults true but is
     *   currently a no-op: there is no per-topic history endpoint yet, so on
     *   switch the topic's bucket starts empty and fills from the live stream.
     *   Kept as a parameter so a future GET /topics/{id}/history slots in here.
     */
    _resubscribe({ loadHistory = true } = {}) {
        // tear down the previous subscription
        this._subHandle?.dispose();
        this._subHandle = null;
        if (!this.activeTopicId) return;

        // History loading is intentionally a no-op for now — see JSDoc above.
        // The bucket will populate from the live stream as events arrive.
        if (loadHistory) {
            // no-op: per-topic history endpoint not yet wired
        }

        // open the subscription — always via topic fan-in (a single-agent topic
        // is just a team of one; same code path, no branching).
        const spec = { topic: this.activeTopicId };
        this._subHandle = this.streamClient.subscribe(spec, {
            onEvent: (e) => this._dispatchEvent(e),
            onDone: () => {
                /* the view-level stream ended; per-topic running cleared by done events */
            },
            onError: () => {
                /* EventSource auto-reconnects; surface nothing by default */
            },
        });
    }

    /** Last assistant text of a topic's bucket (for the list preview). */
    _lastAssistantText(topicId) {
        const msgs = this.messageStore.get(topicId);
        for (let i = msgs.length - 1; i >= 0; i--) {
            const m = msgs[i];
            if (m.role !== "assistant") continue;
            for (const p of m.content || []) {
                if (p.type === "text" && p.text) {
                    return p.text.replace(/\s+/g, " ").trim().slice(0, 80);
                }
            }
        }
        return "";
    }
}

/**
 * Find the newest DERIVED topic (team / top-level subagent) not in beforeIds.
 * Used to auto-switch to the task the main topic just delegated: instead of
 * trusting a parent field (which can be missing), we diff the topic list
 * before vs after reload and grab any new derived topic. Picks the most
 * recently updated one if several appeared.
 *
 * Each item is a topic object: { id, title, agent_name, kind, status, preview,
 * session_id, workdir, created_at, updated_at }.
 */
function _newestDerived(list, beforeIds) {
    // Skip the main topic — we only care about derived work.
    const fresh = (list || []).filter((t) => {
        if (!t || t.id === "main") return false;
        return !beforeIds.has(t.id);
    });
    if (!fresh.length) return null;
    return fresh.sort((a, b) => {
        const ta = _ts(a.updated_at || a.created_at);
        const tb = _ts(b.updated_at || b.created_at);
        return tb - ta;
    })[0];
}

function _ts(s) {
    if (!s) return 0;
    return Date.parse(String(s).replace(" ", "T")) || 0;
}
