/**
 * agentRuntime — the facade: orchestrates store + client + reducer, exposes
 * observable state and actions. This is the ONLY object the view layer touches.
 *
 * Responsibilities (pure orchestration — it owns no domain logic itself):
 *   - track which session/scope is currently being observed
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

import { MessageStore } from "./messageStore.js";
import { StreamClient } from "./streamClient.js";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

// Team member cache — OUTSIDE mobx so writing it never triggers computed
// re-runs (the team-view freeze was an infinite loop otherwise).
const _scopeMembersCache = {};

export class AgentRuntime {
  /** @type {MessageStore} */
  messageStore = new MessageStore();
  /** @type {StreamClient} */
  streamClient = new StreamClient();

  // ─── injected collaborators ──────────────────────────────────────────────
  /** @type {null | { sessions: any[], bumpActivity: Function, markRunning: Function, markStatus: Function }} */
  _sessionStore = null;

  // ─── internal handles (NOT observable — prefixed _) ─────────────────────
  _subHandle = null;                 // current SSE subscription handle
  _sendAborts = {};                  // session_id → AbortController (for stop)
  _preSendSessionIds = null;         // session id snapshot before a manus turn (for _afterDelegation diff)
  // scope_id → [session_id] cache for team merging. Lives OUTSIDE mobx (module
  // level) so writing it never triggers computed re-runs — the team-view freeze
  // was an infinite loop: computed read it → refresh wrote it → re-run.
  // Access via the module-level _scopeMembersCache.

  // ─── observable state ───────────────────────────────────────────────────
  /** The session the user is focused on. */
  activeSessionId = null;
  /** When set, the view is the team group-chat (fan-in of this scope's members). */
  activeScopeId = null;
  /** session_id → bool: a run is currently streaming for that session. */
  runningBySession = {};
  /** last error message, if any. */
  error = null;

  constructor() {
    makeAutoObservable(this);
    if (typeof window !== "undefined") window.__rt = this; // DEBUG
  }

  /** Inject the SessionStore (for list unread/preview/status sync). Optional. */
  setSessionStore(s) {
    this._sessionStore = s;
  }

  // ─── observable views (computed) ─────────────────────────────────────────

  /** Messages for the current view: one session, or the team's merged timeline. */
  get activeMessages() {
    if (this.activeScopeId) {
      return this._mergedScopeMessages(this.activeScopeId);
    }
    return this.messageStore.get(this.activeSessionId);
  }

  /** Is anything in the current view actively streaming? */
  get isRunning() {
    if (this.activeScopeId) {
      const members = _scopeMembersCache[this.activeScopeId] || [];
      return members.some((sid) => this.runningBySession[sid]);
    }
    return !!this.runningBySession[this.activeSessionId];
  }

  // ─── actions ─────────────────────────────────────────────────────────────

  /**
   * Switch what the user is observing.
   * @param {string} sessionId  the focus session
   * @param {string|null} scopeId  null = single session; set = team fan-in view
   */
  setActive(sessionId, scopeId = null) {
    this.activeSessionId = sessionId;
    this.activeScopeId = scopeId;
    // Rebuild the live subscription for the new view (async history load first).
    this._resubscribe();
  }

  /**
   * User sends a message: trigger the agent run (background POST), optimistically
   * show the user bubble, and ensure we're subscribed to receive the output.
   */
  async send(sessionId, text) {
    if (!text || !text.trim()) return;

    // Snapshot session ids BEFORE the turn — used by _afterDelegation to detect
    // NEW sessions created during this turn (dispatch may create team/subagent
    // sessions, and the session list may get reloaded mid-turn, so we can't
    // diff against the live list at _endRun time).
    this._preSendSessionIds = new Set(
      (this._sessionStore?.sessions || []).map((s) => s.id)
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
    this._sessionStore?.markRunning?.(sessionId);

    // 2. Rebuild the subscription BEFORE triggering the run. The server starts
    //    the run the instant POST is received (async), so events can appear the
    //    moment POST returns. If we re-subscribe AFTER POST (as we once did),
    //    early events are lost to the old (already-done) drain / a reconnecting
    //    EventSource. Building the drain first guarantees every event is caught.
    const inView =
      this.activeScopeId
        ? (this.activeSessionId === sessionId ||
           (_scopeMembersCache[this.activeScopeId] || []).includes(sessionId))
        : (this.activeSessionId === sessionId);
    if (inView) {
      // Rebuild the subscription WITHOUT reloading history: the session's
      // messages are already in the store (incl. the optimistic user bubble
      // just appended), and a history fetch would overwrite that bubble.
      this._resubscribe({ loadHistory: false });
    } else {
      this.streamClient.subscribe({ sessions: [sessionId] }, {
        onEvent: (e) => this._dispatchEvent(e),
      });
    }

    // 3. POST to trigger the run (does NOT stream back — events arrive via the
    //    subscription built above). AbortController lets stop() cancel it.
    const ac = new AbortController();
    this._sendAborts[sessionId] = ac;
    try {
      const res = await fetch(`${BACKEND}/sessions/${encodeURIComponent(sessionId)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
        signal: ac.signal,
      });
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
      // In team view, a new member agent may appear mid-run (teamleader
      // dispatches coder/researcher). Add its session_id directly to the member
      // cache so the merged view picks it up. We DON'T call _refreshScopeMembers
      // (which reads SessionStore.sessions) because that list may not have been
      // reloaded yet — the event's session_id is authoritative.
      if (this.activeScopeId && sid && sid !== this.activeScopeId) {
        const members = _scopeMembersCache[this.activeScopeId] || [];
        if (!members.includes(sid)) {
          _scopeMembersCache[this.activeScopeId] = [...members, sid];
        }
      }
    });
  }

  /** Mark a session's run as finished + sync the session list. */
  _endRun(sessionId) {
    runInAction(() => {
      this.runningBySession[sessionId] = false;
    });
    if (this._sessionStore) {
      const preview = this._lastAssistantText(sessionId);
      const isActive =
        (this.activeScopeId ? false : this.activeSessionId === sessionId) ||
        (this.activeScopeId && (_scopeMembersCache[this.activeScopeId] || []).includes(sessionId) && this.activeSessionId === sessionId);
      this._sessionStore.bumpActivity?.(sessionId, {
        unread: isActive ? 0 : 1,
        preview,
        speaker: "assistant",
      });
      this._sessionStore.markStatus?.(sessionId, "active");
    }
    // When the DEFAULT entry's turn ends, the agent may have dispatched a new
    // sub-agent / team (via the dispatch tool). Refresh the session list so the
    // new child appears without a manual page reload, then auto-switch to it
    // so the user lands on the delegated work.
    if (sessionId === "manus") {
      this._afterDelegation().catch(() => {});
    }
  }

  /**
   * After a default-agent turn: reload the session list and, if a NEW derived
   * session (team / top-level subagent) appeared, switch the view to it.
   * Detects "new" by diffing the id set before vs after the reload — more
   * reliable than trusting a parent field.
   */
  async _afterDelegation() {
    if (!this._sessionStore) return;
    // Use the snapshot taken at send() time — NOT the live list (which may
    // have been reloaded mid-turn, already containing the new sessions).
    const before = this._preSendSessionIds || new Set();
    this._preSendSessionIds = null;
    const list = await this._sessionStore.load();
    const child = _newestDerived(list, before);
    if (child) {
      // switching view also rebuilds the subscription + loads history
      this.setActive(child.id, child.kind === "team" ? child.id : null);
      this._sessionStore.select(child.id);
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
      if (this.activeScopeId) {
        this._refreshScopeMembers(this.activeScopeId);
        for (const sid of _scopeMembersCache[this.activeScopeId] || []) {
          this._loadHistory(sid);
        }
      }
    }

    // open the subscription (scope mode for teams, sessions mode otherwise)
    const spec = this.activeScopeId
      ? { scope: this.activeScopeId }
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
      const res = await fetch(`${BACKEND}/sessions/${encodeURIComponent(sessionId)}`);
      if (!res.ok) return;
      const data = await res.json();
      runInAction(() => {
        this.messageStore.set(sessionId, data.messages || []);
      });
    } catch {
      /* best-effort; history reload can retry on next switch */
    }
  }

  /** Refresh the cached member list for a scope from the session store. */
  _refreshScopeMembers(scopeId) {
    if (!this._sessionStore) return;
    const members = [scopeId];
    for (const s of this._sessionStore.sessions) {
      if (s.scope_id === scopeId) members.push(s.id);
    }
    _scopeMembersCache[scopeId] = Array.from(new Set(members));
  }

  /** Merge a scope's member sessions into one timeline (deduped + time-sorted). */
  _mergedScopeMessages(scopeId) {
    const cached = _scopeMembersCache[scopeId];
    const ids = cached || [scopeId];
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
    // (teamleader → researcher → teamleader → coder ...), not grouped by agent.
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
 * Find the newest DERIVED session (team / top-level subagent) not in beforeIds.
 * Used to auto-switch to the task the default agent just delegated: instead of
 * trusting a parent field (which can be missing), we diff the session list
 * before vs after reload and grab any new derived session. Picks the most
 * recently updated one if several appeared.
 */
function _newestDerived(list, beforeIds) {
  const fresh = (list || []).filter(
    (s) =>
      (s.kind === "team" || (s.kind === "subagent" && !s.scope_id)) &&
      !beforeIds.has(s.id),
  );
  if (!fresh.length) return null;
  return fresh.sort((a, b) => {
    const ta = Date.parse((a.updated_at || a.created_at || "").replace(" ", "T")) || 0;
    const tb = Date.parse((b.updated_at || b.created_at || "").replace(" ", "T")) || 0;
    return tb - ta;
  })[0];
}
