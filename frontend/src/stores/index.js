import { TopicStore } from "./topic-store";
import { AgentStore } from "./agent-store";
import { SkillStore } from "./skill-store";
import { SandboxStore } from "./sandbox-store";
import { AgentRuntime } from "@/runtime/agent-runtime";

export class RootStore {
    topics;
    runtime;
    sandbox;
    agentStore;
    skillStore;

    constructor() {
        this.topics = new TopicStore();
        this.runtime = new AgentRuntime();
        this.sandbox = new SandboxStore();
        this.agentStore = new AgentStore();
        this.skillStore = new SkillStore();
        this.runtime.setTopicStore(this.topics);
        this.sandbox.setTopicStore(this.topics);
        this.runtime.setSandboxStore(this.sandbox);
    }
}

/** Process-wide singleton. */
export const rootStore = new RootStore();
