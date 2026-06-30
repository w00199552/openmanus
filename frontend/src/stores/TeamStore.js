import { makeAutoObservable, runInAction } from "mobx";

import {
  getTeamMessages,
  postTeamMessage,
  subscribeTeam,
} from "@/services/teamService";

/**
 * TeamStore owns the live team group-chat view.
 *
 * When a team session is opened, we load its history and subscribe to the SSE
 * stream. Incoming GROUP_MESSAGE events append to `messages`; non-group AG-UI
 * frames (tool calls etc.) are folded into the last speaker's message as
 * "details" (rendered collapsed).
 *
 * Views call actions here; never the service directly.
 */
export class TeamStore {
  activeTeamId = null;
  messages = []; // [{id, speaker, text, direction, collapsed, details:[]}]
  status = "idle"; // idle | loading | running | done | error
  error = null;
  _sub = null; // current SSE subscription
  // ref to SessionStore (injected by RootStore) so incoming group messages can
  // bump the team's activity + unread. null until wired.
  _sessions = null;

  constructor() {
    makeAutoObservable(this);
  }

  /** Injected by RootStore to avoid a circular import. */
  setSessionStore(sessions) {
    this._sessions = sessions;
  }

  /** Open a team: load history + subscribe to live stream. */
  async open(teamId) {
    // tear down any previous subscription
    this._dispose();

    this.activeTeamId = teamId;
    this.messages = [];
    this.status = "loading";
    this.error = null;

    try {
      const data = await getTeamMessages(teamId);
      runInAction(() => {
        this.messages = (data.messages || []).map((m) => ({
          id: m.id,
          speaker: m.speaker,
          text: m.text,
          direction: m.direction,
          collapsed: m.speaker !== "user", // user msgs expanded, others collapsed
          details: [],
        }));
        this.status = data.status === "done" ? "done" : "running";
      });
    } catch (e) {
      runInAction(() => {
        this.error = e.message || String(e);
        this.status = "error";
      });
      return;
    }

    // subscribe to live updates (only meaningful if still running)
    if (this.status === "running") {
      this._sub = subscribeTeam(teamId, {
        onGroup: (msg) => this._appendGroup(msg),
        onFrame: (payload) => this._handleFrame(payload),
        onDone: () => runInAction(() => (this.status = "done")),
        onError: () =>
          runInAction(() => {
            this.error = "stream error";
          }),
      });
    }
  }

  /** Close the team view + stop the SSE subscription. */
  close() {
    this._dispose();
    this.activeTeamId = null;
    this.messages = [];
    this.status = "idle";
  }

  /** User posts a message into the team. */
  async sendMessage(text, targetAgent = null) {
    if (!this.activeTeamId || !text.trim()) return;
    // optimistic: show the user's message immediately
    this.messages.push({
      id: `u-${Date.now()}`,
      speaker: "user",
      text,
      direction: targetAgent ? "mention" : "chat",
      collapsed: false,
      details: [],
    });
    try {
      await postTeamMessage(this.activeTeamId, {
        content: text,
        targetAgent,
      });
    } catch (e) {
      this.error = e.message || String(e);
    }
  }

  /** Toggle a message's collapsed state (expand/collapse sub-agent detail). */
  toggleCollapse(id) {
    const m = this.messages.find((x) => x.id === id);
    if (m) m.collapsed = !m.collapsed;
  }

  // --- internal handlers ---

  _appendGroup(msg) {
    runInAction(() => {
      const id = msg.messageId || `g-${Date.now()}`;
      const existing = this.messages.find((m) => m.id === id);

      // STREAMING DELTA: append text to an existing streaming message
      // (mirrors AG-UI TEXT_MESSAGE_CONTENT under a stable messageId). Uses
      // immutable replacement so mobx observers re-render on each token.
      if (msg.delta != null) {
        if (existing) {
          const i = this.messages.indexOf(existing);
          this.messages[i] = { ...existing, text: existing.text + msg.delta };
        }
        return; // a delta never bumps activity/preview (too high frequency)
      }

      // DETAIL: a tool-call step appended to an existing message's details
      // (e.g. a sub-agent's read_file/write_file, shown under its own speaker).
      if (msg.detail != null) {
        if (existing) {
          const i = this.messages.indexOf(existing);
          this.messages[i] = {
            ...existing,
            details: [...existing.details, msg.detail],
          };
        }
        return;
      }

      // CLOSE / overwrite: replace an existing streaming message with the
      // final full text (no duplicate bubble).
      if (existing && msg.content != null) {
        const i = this.messages.indexOf(existing);
        this.messages[i] = {
          ...existing,
          text: msg.content,
          streaming: false,
        };
      } else {
        // NEW message (or open of a stream).
        this.messages.push({
          id,
          speaker: msg.speaker || "agent",
          text: msg.content || "",
          direction: msg.direction || "chat",
          collapsed: msg.speaker !== "user",
          streaming: !!msg.streaming,
          details: [],
        });
      }

      // a (non-delta) group message arrived: bump the team's activity in the
      // list. +1 unread only if the user isn't currently viewing this team.
      // The message text becomes the list preview (2nd line).
      if (this.activeTeamId && this._sessions) {
        const isActive = this._sessions.activeId === this.activeTeamId;
        const preview = (msg.content || "").replace(/\s+/g, " ").trim().slice(0, 80);
        this._sessions.bumpActivity(this.activeTeamId, {
          unread: isActive ? 0 : 1,
          preview,
          speaker: msg.speaker,
        });
      }
    });
  }

  _handleFrame(payload) {
    // Fold tool-call / text-token frames into the last agent message as detail.
    // For MVP we just track them as opaque detail entries on the last non-user
    // message, which the UI renders collapsed.
    runInAction(() => {
      const last = [...this.messages].reverse().find((m) => m.speaker !== "user");
      if (!last) return;
      if (payload.type === "TOOL_CALL_START") {
        last.details.push(`🔧 ${payload.toolCallName || "tool"}`);
      }
    });
  }

  _dispose() {
    if (this._sub) {
      this._sub.dispose();
      this._sub = null;
    }
  }
}
