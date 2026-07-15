import { makeAutoObservable, runInAction } from "mobx";

import * as sessionApi from "@/services/sessionService";

const LS_KEY = "openmanus.activeSessionId";

// One-time migration: copy the old "deepopen.*" localStorage keys to the new
// "openmanus.*" namespace so existing users keep their active session + layout.
_migrateLsKey("deepopen.activeSessionId", LS_KEY);
function _migrateLsKey(oldKey, newKey) {
    if (localStorage.getItem(newKey) != null) return; // already migrated
    const v = localStorage.getItem(oldKey);
    if (v != null) localStorage.setItem(newKey, v);
}

/**
 * The fixed id of the single, permanent "Default Agent" entry. It is always
 * visible in the list, cannot be deleted, and is where the user talks to the
 * entry/router agent. "New chat" RESETS its history (deletes the checkpointer
 * thread), it does NOT create a second default.
 */
export const DEFAULT_ID = "manus";

/**
 * SessionStore owns the conversation list + the active session id.
 *
 * The active session id is THE thing that makes memory work: it's sent with
 * every agent message so the backend checkpointer keeps one continuous thread.
 *
 * LIST MODEL — one permanent default + tasks:
 *   - DEFAULT group: the single "default" entry (always shown, never deleted).
 *     New chat resets its history rather than spawning a new default.
 *   - TASKS & TEAMS group: team + subagent sessions (derived work). These come
 *     and go; dispatching from default adds one here.
 *   - When the active session is a task (the user auto-switched to a Coder),
 *     the default item stays in the list so the user can always get back.
 *   - Status lives ON each item: pulse dot while running, red badge for unread.
 *
 * Views call actions here; they never call the service directly.
 */
export class SessionStore {
    sessions = [];
    activeId = null;
    loading = false;
    error = null;
    // sessionId -> unread message count (cleared on select)
    unread = {};

    constructor() {
        makeAutoObservable(this);
        // The default session is the permanent entry; pin to it on a cold boot.
        this.activeId = localStorage.getItem(LS_KEY) || DEFAULT_ID;
    }

    get active() {
        return this.sessions.find((s) => s.id === this.activeId) || null;
    }

    /** Is the active session the default entry? */
    get isActiveDefault() {
        return this.activeId === DEFAULT_ID;
    }

    /** Sessions sorted by last-activity time, most recent first (default pinned top). */
    get sortedSessions() {
        return [...this.sessions].sort((a, b) => {
            // the default entry always floats to the very top of its group
            const ad = a.id === DEFAULT_ID ? 1 : 0;
            const bd = b.id === DEFAULT_ID ? 1 : 0;
            if (ad !== bd) return bd - ad;
            const ta = _ts(a.updated_at) || _ts(a.created_at) || 0;
            const tb = _ts(b.updated_at) || _ts(b.created_at) || 0;
            return tb - ta;
        });
    }

    /**
     * Root sessions shown in the DEFAULT group. The default entry is ALWAYS shown
     * (even when the user is viewing a task), so they can always get back to it.
     */
    get rootSessions() {
        return this.sortedSessions.filter((s) => s.kind === "root");
    }

    /**
     * Derived work shown in the TASKS & TEAMS group. Teams always show (they're
     * scope roots the user can open as group chats). A subagent shows here only
     * if it was dispatched DIRECTLY from the default entry (top-level single
     * task, scope_id is NULL) — subagents living INSIDE a team (scope_id = the
     * team id) are team-internal execution detail and are viewed via the team's
     * scope fan-in, so they're hidden from the top-level list.
     */
    get taskSessions() {
        return this.sortedSessions.filter(
            (s) => s.kind === "team" || (s.kind === "subagent" && !s.scope_id)
        );
    }

    /** Unread count for a session (0 if none / not tracked). */
    unreadCount(id) {
        return this.unread[id] || 0;
    }

    /**
     * Mark a session as running right now (spinner in the list), locally.
     * Called by the runtime when a turn starts so the list reflects it
     * instantly without waiting for the backend status update. Cleared by
     * bumpActivity on turn end.
     */
    markRunning(id) {
        const s = this.sessions.find((x) => x.id === id);
        if (s) s.status = "running";
    }

    /** Set a session's status locally (e.g. "active" when a subagent finishes). */
    markStatus(id, status) {
        const s = this.sessions.find((x) => x.id === id);
        if (s) s.status = status;
    }

    _setActive(id) {
        this.activeId = id;
        if (id) localStorage.setItem(LS_KEY, id);
        else localStorage.removeItem(LS_KEY);
        // reading a session clears its unread
        if (id) this.unread[id] = 0;
    }

    /**
     * Mark that a session received new messages (called by the runtime when an
     * agent turn finishes). If the session is NOT the active one, increment its
     * unread and refresh its activity time so it floats to the top of the list.
     *
     * If `preview` is given, it's written into the session row's metadata (for
     * the list's 2nd line) AND persisted server-side via setPreview. The local
     * update is synchronous so the list reflects it immediately.
     */
    bumpActivity(id, { unread = 0, preview, speaker } = {}) {
        const s = this.sessions.find((x) => x.id === id);
        if (!s) return;
        const isActive = this.activeId === id;
        runInAction(() => {
            // refresh activity time so it sorts to the top
            s.updated_at = new Date()
                .toISOString()
                .replace("T", " ")
                .slice(0, 19);
            // turn ended → no longer running
            if (s.status === "running") s.status = "active";
            if (preview) {
                const md = { ...(s.metadata || {}), preview };
                if (speaker) md.preview_speaker = speaker;
                s.metadata = md;
            }
            if (!isActive) {
                this.unread[id] = (this.unread[id] || 0) + unread;
            }
        });
        // persist preview to the backend (best-effort, fire-and-forget)
        if (preview) {
            sessionApi.setPreview(id, preview, speaker).catch(() => {});
        }
    }

    /** Load the session list from the backend (via service). Returns the list. */
    async load() {
        this.loading = true;
        this.error = null;
        try {
            const data = await sessionApi.listSessions();
            runInAction(() => {
                this.sessions = Array.isArray(data) ? data : [];
                this.loading = false;
                // if the restored activeId no longer exists, fall back to the default
                // entry (which is always present / created implicitly on first use).
                if (
                    this.activeId &&
                    this.activeId !== DEFAULT_ID &&
                    !this.sessions.some((s) => s.id === this.activeId)
                ) {
                    this._setActive(DEFAULT_ID);
                }
            });
            return this.sessions;
        } catch (e) {
            runInAction(() => {
                this.error = e.message || String(e);
                this.loading = false;
            });
            return [];
        }
    }

    /** Create a new conversation and switch to it. Returns the session. */
    async create(title) {
        const s = await sessionApi.createSession({ title });
        runInAction(() => {
            // dedupe: avoid a duplicate if load() later returns the same id
            if (!this.sessions.some((x) => x.id === s.id)) {
                this.sessions.unshift(s);
            }
            this._setActive(s.id);
        });
        return s;
    }

    /**
     * "New chat" for the default entry: RESET its history (delete the
     * checkpointer thread) and clear the local timeline. The default item itself
     * stays — it's permanent. This bounds context without spawning new sessions.
     */
    async resetDefault() {
        await sessionApi.resetHistory(DEFAULT_ID).catch(() => {});
        runInAction(() => {
            // clear any preview + reset status on the default row
            const s = this.sessions.find((x) => x.id === DEFAULT_ID);
            if (s) {
                s.metadata = { ...(s.metadata || {}), preview: "" };
                s.status = "active";
            }
            this._setActive(DEFAULT_ID);
        });
    }

    /** Switch the active conversation. */
    select(id) {
        this._setActive(id);
    }

    /** Delete a session and fall back to the default entry if it was active. */
    async remove(id) {
        if (id === DEFAULT_ID) return; // the default entry cannot be deleted
        await sessionApi.deleteSession(id);
        runInAction(() => {
            this.sessions = this.sessions.filter((s) => s.id !== id);
            delete this.unread[id];
            if (this.activeId === id) {
                this._setActive(DEFAULT_ID);
            }
        });
    }

    /** Rename a session. */
    async rename(id, title) {
        const s = await sessionApi.updateSession(id, { title });
        runInAction(() => {
            const idx = this.sessions.findIndex((x) => x.id === id);
            if (idx >= 0) this.sessions[idx] = { ...this.sessions[idx], ...s };
        });
    }
}

/** Parse a "YYYY-MM-DD HH:MM:SS" or ISO timestamp into epoch ms. */
function _ts(s) {
    if (!s) return 0;
    const n = Date.parse(s.replace(" ", "T"));
    return Number.isNaN(n) ? 0 : n;
}
