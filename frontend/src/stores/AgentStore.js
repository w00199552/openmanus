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

  // edit drafts (for the detail page)
  promptDraft = "";
  toolDraft = new Set();

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
      await fetch(`${BACKEND}/agents/${encodeURIComponent(this.current.name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: this.promptDraft, tools: [...this.toolDraft] }),
      });
      // reload the agent to confirm
      await this.selectAgent(this.current.name);
    } catch (e) {
      runInAction(() => { this.error = e.message; });
    }
    runInAction(() => { this.saving = false; });
  }
}
