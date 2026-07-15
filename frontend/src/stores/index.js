import { SessionStore } from "./SessionStore";
import { AgentStore } from "./AgentStore";
import { SkillStore } from "./SkillStore";
import { SandboxStore } from "./SandboxStore";
import { AgentRuntime } from "@/runtime/agentRuntime";

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
