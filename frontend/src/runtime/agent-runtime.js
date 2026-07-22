/**
 * agentRuntime — the facade: orchestrates store + client + reducer, exposes
 * observable state and actions. This is the ONLY object the view layer touches.
 *
 * Responsibilities (pure orchestration — it owns no domain logic itself):
 *   - track which session/topic is currently being observed
 *   - on switch: load history, (re)build the SSE subscription, drain events
 *   - on send: POST to trigger the run (background), optimistic user bubble,
 *     ensure a subscription is receiving the output
 *   - route each incoming event to the right session in the message store
 *   - keep running-state + the session list (unread/preview) in sync
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

// Team member cache — OUTSIDE mobx so writing it never triggers computed
// re-runs (the team-view freeze was an infinite loop otherwise).
const _topicMembersCache = {};

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
    _sendAborts = {}; // session_id → AbortController (for stop)
    _preSendSessionIds = null; // topic id snapshot before a main-topic turn (for _afterDelegation diff)
    // topic_id → [session_id] cache for team merging. Lives OUTSIDE mobx (module
    // level) so writing it never triggers computed re-runs — the team-view freeze
    // was an infinite loop: computed read it → refresh wrote it → re-run.
    // Access via the module-level _topicMembersCache.

    // ─── observable state ───────────────────────────────────────────────────
    /** The session the user is focused on. */
    activeSessionId = null;
    /** When set, the view is the team group-chat (fan-in of this topic's members). */
    activeTopicId = null;
    /** session_id → bool: a run is currently streaming for that session. */
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

    /** Messages for the current view: one session, or the team's merged timeline. */
    get activeMessages() {
        if (this.activeTopicId) {
            return this._mergedTopicMessages(this.activeTopicId);
        }
        return this.messageStore.get(this.activeSessionId);
    }

    /** Is anything in the current view actively streaming? */
    get isRunning() {
        if (this.activeTopicId) {
            const members = _topicMembersCache[this.activeTopicId] || [];
            return members.some((sid) => this.runningBySession[sid]);
        }
        return !!this.runningBySession[this.activeSessionId];
    }

    // ─── actions ─────────────────────────────────────────────────────────────

    /**
     * Switch what the user is observing.
     * @param {string} sessionId  the focus session
     * @param {string|null} topicId  null = single session; set = team fan-in view
     */
    setActive(sessionId, topicId = null) {
        this.activeSessionId = sessionId;
        this.activeTopicId = topicId;
        // Sync sandbox workdir to match the selected topic
        this._sandboxStore?.syncFromTopic();
        // Rebuild the live subscription for the new view (async history load first).
        this._resubscribe();
    }

    /**
     * User sends a message: trigger the agent run (background POST), optimistically
     * show the user bubble, and ensure we're subscribed to receive the output.
     */
    async send(sessionId, text) {
        if (!text || !text.trim()) return;

        // ── cd command: delegate to SandboxStore (doesn't trigger agent) ───
        const trimmed = text.trim();
        const lower = trimmed.toLowerCase();
        if (lower === "cd" || lower.startsWith("cd ")) {
            const path = trimmed.slice(2).trim(); // everything after "cd"
            await this._handleCd(sessionId, path, text);
            return;
        }

        // Snapshot topic ids BEFORE the turn — used by _afterDelegation to detect
        // NEW topics created during this turn (dispatch may create team/subagent
        // topics, and the topic list may get reloaded mid-turn, so we can't
        // diff against the live list at _endRun time).
        this._preSendSessionIds = new Set(
            (this._topicStore?.topics || []).map((t) => t.id)
        );

        // 1. optimistic user bubble
        this.messageStore.appendMessage(sessionId, {
            id: `u-${Date.now()}`,
            role: "user",
            speaker: "user",
            content: [{ type: "text", text }],
            status: "complete",
            createdAt: Date.now(),
        });

        runInAction(() => {
            this.runningBySession[sessionId] = true;
            this.error = null;
        });
        // mark the active topic running (sessionId may not be the topic id;
        // the active topic is what the list surfaces to the user).
        const runningTopicId = this._topicStore?.activeTopicId;
        if (runningTopicId) this._topicStore?.markRunning?.(runningTopicId);

        // 2. Rebuild the subscription BEFORE triggering the run. The server starts
        //    the run the instant POST is received (async), so events can appear the
        //    moment POST returns. If we re-subscribe AFTER POST (as we once did),
        //    early events are lost to the old (already-done) drain / a reconnecting
        //    EventSource. Building the drain first guarantees every event is caught.
        const inView = this.activeTopicId
            ? this.activeSessionId === sessionId ||
              (_topicMembersCache[this.activeTopicId] || []).includes(sessionId)
            : this.activeSessionId === sessionId;
        if (inView) {
            // Rebuild the subscription WITHOUT reloading history: the session's
            // messages are already in the store (incl. the optimistic user bubble
            // just appended), and a history fetch would overwrite that bubble.
            this._resubscribe({ loadHistory: false });
        } else {
            this.streamClient.subscribe(
                { sessions: [sessionId] },
                {
                    onEvent: (e) => this._dispatchEvent(e),
                }
            );
        }

        // 3. POST to trigger the run (does NOT stream back — events arrive via the
        //    subscription built above). AbortController lets stop() cancel it.
        const ac = new AbortController();
        this._sendAborts[sessionId] = ac;
        try {
            const res = await fetch(
                `${BACKEND}/sessions/${encodeURIComponent(sessionId)}/messages`,
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
            this._endRun(sessionId);
            return;
        } finally {
            delete this._sendAborts[sessionId];
        }
    }

    /**
     * Handle a cd command: show user bubble, delegate API call to SandboxStore,
     * then display the system reply. All workdir state is owned by SandboxStore.
     */
    async _handleCd(sessionId, path, originalText) {
        // optimistic user bubble
        this.messageStore.appendMessage(sessionId, {
            id: `u-${Date.now()}`,
            role: "user",
            speaker: "user",
            content: [{ type: "text", text: originalText }],
            status: "complete",
            createdAt: Date.now(),
        });

        try {
            const body = await this._sandboxStore.cd(sessionId, path);
            const reply =
                body.action === "pwd"
                    ? `📁 Current workdir: ${body.workdir}`
                    : `📁 Workdir switched to: ${body.workdir}`;
            this.messageStore.appendMessage(sessionId, {
                id: `cd-${Date.now()}`,
                role: "assistant",
                speaker: "system",
                content: [{ type: "text", text: reply }],
                status: "complete",
                createdAt: Date.now(),
            });
        } catch (e) {
            this.messageStore.appendMessage(sessionId, {
                id: `cd-err-${Date.now()}`,
                role: "assistant",
                speaker: "system",
                content: [{ type: "text", text: `❌ ${e.message}` }],
                status: "complete",
                createdAt: Date.now(),
            });
        }
    }

    /** Stop an in-flight run for a session (aborts the POST + clears running). */
    stop(sessionId = this.activeSessionId) {
        const ac = this._sendAborts[sessionId];
        if (ac) ac.abort();
        this._endRun(sessionId);
    }

    /** Clear a session's messages (e.g. on "new chat" reset). */
    clear(sessionId) {
        this.messageStore.clear(sessionId);
    }

    // ─── internals ───────────────────────────────────────────────────────────

    /**
     * Route one incoming event to its session in the store + update running state.
     * Called by the streamClient subscription callback.
     */
    _dispatchEvent(event) {
        runInAction(() => {
            const sid = event.session_id;
            if (sid) this.messageStore.applyEvent(sid, event);
            // done → that session's run finished
            if (event.kind === "done" && sid) {
                this._endRun(sid);
            }
            if (event.kind === "error") {
                this.error = event.message || "agent error";
            }
            // In team view, a new member agent may appear mid-run (TeamLeader
            // dispatches Coder/Researcher). Add its session_id directly to the member
            // cache so the merged view picks it up. We DON'T call _refreshTopicMembers
            // (which reads TopicStore.topics) because that list may not have been
            // reloaded yet — the event's session_id is authoritative.
            if (this.activeTopicId && sid && sid !== this.activeTopicId) {
                const members = _topicMembersCache[this.activeTopicId] || [];
                if (!members.includes(sid)) {
                    _topicMembersCache[this.activeTopicId] = [...members, sid];
                }
            }
        });
    }

    /** Mark a session's run as finished + sync the topic list. */
    _endRun(sessionId) {
        runInAction(() => {
            this.runningBySession[sessionId] = false;
        });
        // The list is keyed by topic id, not session id. The active topic is the
        // one the user is currently looking at, so attribute activity to it.
        const topicId = this._topicStore?.activeTopicId;
        if (topicId) {
            const preview = this._lastAssistantText(sessionId);
            const isActive =
                this.activeSessionId === sessionId ||
                (this.activeTopicId &&
                    (_topicMembersCache[this.activeTopicId] || []).includes(
                        sessionId
                    ) &&
                    this.activeSessionId === sessionId);
            this._topicStore.bumpActivity?.(topicId, {
                unread: isActive ? 0 : 1,
                preview,
                speaker: "assistant",
            });
            this._topicStore.markStatus?.(topicId, "active");
        }
        // When the main topic's turn ends, the agent may have dispatched a new
        // sub-agent / team (via the dispatch tool). Refresh the topic list so the
        // new child appears without a manual page reload, then auto-switch to it
        // so the user lands on the delegated work.
        if (sessionId === "manus") {
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
        const before = this._preSendSessionIds || new Set();
        this._preSendSessionIds = null;
        const list = await this._topicStore.load();
        const child = _newestDerived(list, before);
        if (child) {
            // child is a topic: child.id = topic_id, child.session_id = focus session.
            // For team topics the topic_id fans-in member sessions; for a single
            // subagent topic, just observe its session.
            const isTeam = child.kind === "team";
            this.setActive(child.session_id || child.id, isTeam ? child.id : null);
            this._topicStore.select(child.id);
        }
    }

    /**
     * Rebuild the live SSE subscription for the current view.
     * @param {{ loadHistory?: boolean }} opts — loadHistory defaults true; pass
     *   false on `send` (the session's history is already in the store, and a
     *   re-fetch would overwrite the just-inserted optimistic user bubble).
     */
    _resubscribe({ loadHistory = true } = {}) {
        // tear down the previous subscription
        this._subHandle?.dispose();
        this._subHandle = null;
        if (!this.activeSessionId) return;

        // load history for the focus session (and, in team view, its members)
        if (loadHistory) {
            this._loadHistory(this.activeSessionId);
            if (this.activeTopicId) {
                this._refreshTopicMembers(this.activeTopicId);
                for (const sid of _topicMembersCache[this.activeTopicId] ||
                    []) {
                    this._loadHistory(sid);
                }
            }
        }

        // open the subscription (topic mode for teams, sessions mode otherwise)
        const spec = this.activeTopicId
            ? { topic: this.activeTopicId }
            : { sessions: [this.activeSessionId] };
        this._subHandle = this.streamClient.subscribe(spec, {
            onEvent: (e) => this._dispatchEvent(e),
            onDone: () => {
                /* the view-level stream ended; per-session running cleared by done events */
            },
            onError: () => {
                /* EventSource auto-reconnects; surface nothing by default */
            },
        });
    }

    /** Load a session's history into the store (once). */
    async _loadHistory(sessionId) {
        if (!sessionId || this.messageStore.isLoaded(sessionId)) return;
        try {
            const res = await fetch(
                `${BACKEND}/sessions/${encodeURIComponent(sessionId)}`
            );
            if (!res.ok) return;
            const data = await res.json();
            runInAction(() => {
                this.messageStore.set(sessionId, data.messages || []);
            });
        } catch {
            /* best-effort; history reload can retry on next switch */
        }
    }

    /** Refresh the cached member list for a topic from the topic store. */
    _refreshTopicMembers(topicId) {
        if (!this._topicStore) return;
        const members = [topicId];
        const active = this._topicStore.active;
        if (active && active.id === topicId && active.session_id) {
            members.push(active.session_id);
        }
        // Members of a team are the sessions belonging to the same topic. The
        // topic list only exposes the latest session per topic, so this list is
        // a starting point — additional members surface via event dispatch in
        // _dispatchEvent (which adds any unseen session_id directly to the cache).
        _topicMembersCache[topicId] = Array.from(new Set(members));
    }

    /** Merge a topic's member sessions into one timeline (deduped + time-sorted). */
    _mergedTopicMessages(topicId) {
        const cached = _topicMembersCache[topicId];
        const ids = cached || [topicId];
        const merged = [];
        const seen = new Set();
        for (const sid of ids) {
            for (const m of this.messageStore.get(sid)) {
                if (!seen.has(m.id)) {
                    seen.add(m.id);
                    merged.push(m);
                }
            }
        }
        // Sort by createdAt so messages interleave across agents by time
        // (TeamLeader → Researcher → TeamLeader → Coder ...), not grouped by agent.
        merged.sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0));
        return merged;
    }

    /** Last assistant text of a session (for the list preview). */
    _lastAssistantText(sessionId) {
        const msgs = this.messageStore.get(sessionId);
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
