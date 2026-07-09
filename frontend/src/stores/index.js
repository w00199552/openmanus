import {SessionStore} from "./SessionStore";
import {AgentStore} from "./AgentStore";
import {SkillStore} from "./SkillStore";
import {AgentRuntime} from "@/runtime/agentRuntime";

export class RootStore {
  sessions;
  runtime;
  agentStore;
  skillStore;

  constructor() {
    this.sessions = new SessionStore();
    this.runtime = new AgentRuntime();
    this.agentStore = new AgentStore();
    this.skillStore = new SkillStore();
    this.runtime.setSessionStore(this.sessions);
  }
}

/** Process-wide singleton. */
export const rootStore = new RootStore();
