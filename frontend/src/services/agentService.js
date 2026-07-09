/**
 * Agent service — CRUD for agent configurations (backed by ~/.openmanus/agents/).
 */

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

/** List all agents (metadata only, no prompt body). */
export async function listAgents() {
  const res = await fetch(`${BACKEND}/agents`);
  if (!res.ok) throw new Error(`listAgents: ${res.status}`);
  return res.json();
}

/** Get one agent's full config (including prompt text). */
export async function getAgent(name) {
  const res = await fetch(`${BACKEND}/agents/${encodeURIComponent(name)}`);
  if (!res.ok) throw new Error(`getAgent: ${res.status}`);
  return res.json();
}

/** List all available tools (built-in + user-defined). */
export async function listTools() {
  const res = await fetch(`${BACKEND}/agents/meta/tools`);
  if (!res.ok) throw new Error(`listTools: ${res.status}`);
  return res.json();
}

/** List all available skills. */
export async function listSkills() {
  const res = await fetch(`${BACKEND}/skills`);
  if (!res.ok) throw new Error(`listSkills: ${res.status}`);
  return res.json();
}

/** Get the file tree of a skill. */
export async function getSkillTree(name) {
  const res = await fetch(`${BACKEND}/skills/${encodeURIComponent(name)}/tree`);
  if (!res.ok) throw new Error(`getSkillTree: ${res.status}`);
  return res.json();
}

/** Read a single file from a skill. */
export async function getSkillFile(name, path) {
  const res = await fetch(`${BACKEND}/skills/${encodeURIComponent(name)}/file?path=${encodeURIComponent(path)}`);
  if (!res.ok) throw new Error(`getSkillFile: ${res.status}`);
  return res.json();
}
