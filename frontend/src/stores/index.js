import { SessionStore } from "./SessionStore";
import { AgentStore } from "./AgentStore";
import { AgentRuntime } from "@/runtime/agentRuntime";

export class RootStore {
  sessions;
  runtime;
  agentStore;

  constructor() {
    this.sessions = new SessionStore();
    this.runtime = new AgentRuntime();
    this.agentStore = new AgentStore();
    this.runtime.setSessionStore(this.sessions);
  }
}

/** Process-wide singleton. */
export const rootStore = new RootStore();
