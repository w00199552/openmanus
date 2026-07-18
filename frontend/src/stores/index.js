import { SessionStore } from "./session-store";
import { AgentStore } from "./agent-store";
import { SkillStore } from "./skill-store";
import { SandboxStore } from "./sandbox-store";
import { AgentRuntime } from "@/runtime/agent-runtime";

export class RootStore {
    sessions;
    runtime;
    sandbox;
    agentStore;
    skillStore;

    constructor() {
        this.sessions = new SessionStore();
        this.runtime = new AgentRuntime();
        this.sandbox = new SandboxStore();
        this.agentStore = new AgentStore();
        this.skillStore = new SkillStore();
        this.runtime.setSessionStore(this.sessions);
        this.sandbox.setSessionStore(this.sessions);
        this.runtime.setSandboxStore(this.sandbox);
    }
}

/** Process-wide singleton. */
export const rootStore = new RootStore();
