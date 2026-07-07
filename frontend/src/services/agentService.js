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
