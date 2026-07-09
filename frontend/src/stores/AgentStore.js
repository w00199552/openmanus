import {makeAutoObservable, runInAction} from "mobx";

import {getAgent, listAgents, listSkills, listTools} from "@/services/agentService";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

/**
 * AgentStore — manages agent configurations (list / detail / tools / save).
 * Views call actions here, never services directly.
 */
export class AgentStore {
  agents = [];
  tools = [];
  skills = [];
  current = null;
  loading = false;
  saving = false;
  error = null;
  toast = null;

  // edit drafts
  promptDraft = "";
  toolDraft = new Set();
  skillDraft = new Set();

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

  /** Load all available skills. */
  async loadSkills() {
    try {
      const data = await listSkills();
      runInAction(() => { this.skills = data; });
    } catch { /* ignore */ }
  }

  /** Open an agent's detail (loads full config + tools + skills). */
  async selectAgent(name) {
    this.loading = true;
    try {
      const [agent, tools, skills] = await Promise.all([getAgent(name), listTools(), listSkills()]);
      runInAction(() => {
        this.current = agent;
        this.tools = tools;
        this.skills = skills;
        this.promptDraft = agent.prompt || "";
        this.toolDraft = new Set(agent.tools || []);
        this.skillDraft = new Set(agent.skills || []);
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

  toggleSkill(name) {
    if (this.skillDraft.has(name)) this.skillDraft.delete(name);
    else this.skillDraft.add(name);
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
        body: JSON.stringify({ prompt: this.promptDraft, tools: [...this.toolDraft], skills: [...this.skillDraft] }),
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

  /** Create a new agent on disk. Returns true on success. */
  async create(name, prompt, tools, skills = []) {
    this.saving = true;
    try {
      const res = await fetch(`${BACKEND}/agents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, prompt, tools }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `create failed: ${res.status}`);
      }
      await this.loadAgents();
      this._showToast("success", `Agent "${name}" created`);
      return true;
    } catch (e) {
      this._showToast("error", e.message || "Create failed");
      return false;
    }
    runInAction(() => { this.saving = false; });
  }

  /** Delete a custom agent. Returns true on success. */
  async remove(name) {
    try {
      const res = await fetch(`${BACKEND}/agents/${encodeURIComponent(name)}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `delete failed: ${res.status}`);
      }
      await this.loadAgents();
      this._showToast("success", `Agent "${name}" deleted`);
      return true;
    } catch (e) {
      this._showToast("error", e.message || "Delete failed");
      return false;
    }
  }
}
