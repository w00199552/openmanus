import { makeAutoObservable, runInAction } from "mobx";

import { listAgents, getAgent, listTools } from "@/services/agentService";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

/**
 * AgentStore — manages agent configurations (list / detail / tools / save).
 * Views call actions here, never services directly.
 */
export class AgentStore {
  agents = [];
  tools = [];
  current = null;        // selected agent detail (with prompt)
  loading = false;
  saving = false;
  error = null;
  toast = null;          // { type: "success"|"error", message: string } or null

  // edit drafts (for the detail page)
  promptDraft = "";
  toolDraft = new Set();

  _showToast(type, message) {
    this.toast = { type, message };
    setTimeout(() => { runInAction(() => { this.toast = null; }); }, 3000);
  }

  constructor() {
    makeAutoObservable(this);
  }

  /** Load agent list (metadata only). */
  async loadAgents() {
    this.loading = true;
    try {
      const data = await listAgents();
      runInAction(() => { this.agents = data; this.loading = false; });
      return data;
    } catch (e) {
      runInAction(() => { this.error = e.message; this.loading = false; });
    }
  }

  /** Load all available tools (built-in + user). */
  async loadTools() {
    try {
      const data = await listTools();
      runInAction(() => { this.tools = data; });
    } catch { /* ignore */ }
  }

  /** Open an agent's detail (loads full config + tools). */
  async selectAgent(name) {
    this.loading = true;
    try {
      const [agent, tools] = await Promise.all([getAgent(name), listTools()]);
      runInAction(() => {
        this.current = agent;
        this.tools = tools;
        this.promptDraft = agent.prompt || "";
        this.toolDraft = new Set(agent.tools || []);
        this.loading = false;
      });
    } catch (e) {
      runInAction(() => { this.error = e.message; this.loading = false; });
    }
  }

  /** Clear the current detail. */
  clearCurrent() {
    this.current = null;
  }

  // ─── draft mutators (called by view) ────────────────────────────────────

  setPromptDraft(text) {
    this.promptDraft = text;
  }

  toggleTool(name) {
    if (this.toolDraft.has(name)) this.toolDraft.delete(name);
    else this.toolDraft.add(name);
  }

  // ─── save ────────────────────────────────────────────────────────────────

  /** Save prompt + tools to backend (writes agent.yaml + prompt.md on disk). */
  async save() {
    if (!this.current) return;
    this.saving = true;
    try {
      const res = await fetch(`${BACKEND}/agents/${encodeURIComponent(this.current.name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: this.promptDraft, tools: [...this.toolDraft] }),
      });
      if (!res.ok) throw new Error(`save failed: ${res.status}`);
      await this.selectAgent(this.current.name);
      this._showToast("success", "Agent saved successfully");
    } catch (e) {
      runInAction(() => { this.error = e.message; });
      this._showToast("error", e.message || "Save failed");
    }
    runInAction(() => { this.saving = false; });
  }
}
