import { observer } from "mobx-react-lite";
import { useEffect, useState } from "react";
import {
    AlertCircle,
    Bot,
    Check,
    ChevronLeft,
    FileText,
    Lock,
    Save,
    Sparkles,
    Wrench,
} from "lucide-react";
import MDEditor from "@uiw/react-md-editor";

import { useStore } from "@/hooks/use-store";
import { Avatar } from "@/components/avatar";
import { FancyButton } from "@/components/ui/fancy-button";
import { cn } from "@/lib/utils";

/**
 * AgentsView — card grid → click to open config (left tabs: Prompt / Tools).
 * Calls agentStore actions only (view → store → service).
 */
export const AgentsView = observer(function AgentsView() {
    const { agentStore } = useStore();
    const [selected, setSelected] = useState(null);
    const [createMode, setCreateMode] = useState(false);

    useEffect(() => {
        agentStore.loadAgents().then();
    }, [agentStore]);

    const builtinAgents = agentStore.agents.filter((a) => a.is_builtin);
    const customAgents = agentStore.agents.filter((a) => !a.is_builtin);

    if (selected) {
        return (
            <AgentDetail
                name={selected}
                onBack={() => {
                    setSelected(null);
                    agentStore.clearCurrent();
                    agentStore.loadAgents();
                }}
            />
        );
    }

    if (createMode) {
        return (
            <CreateAgent
                onBack={() => setCreateMode(false)}
                onCreated={(name) => {
                    setCreateMode(false);
                    setSelected(name);
                    agentStore.selectAgent(name);
                }}
            />
        );
    }

    if (agentStore.loading) return <Centered>Loading…</Centered>;

    return (
        <div className="h-full overflow-y-auto">
            {agentStore.toast && <Toast {...agentStore.toast} />}
            <div className="mx-auto max-w-5xl px-6 py-8">
                <div className="mb-6 flex items-center justify-between">
                    <Header />
                    <FancyButton onClick={() => setCreateMode(true)}>
                        New Agent
                    </FancyButton>
                </div>

                {/* builtin agents */}
                {builtinAgents.length > 0 && (
                    <>
                        <SectionTitle>Built-in</SectionTitle>
                        <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                            {builtinAgents.map((a) => (
                                <AgentCard
                                    key={a.name}
                                    agent={a}
                                    onClick={() => {
                                        setSelected(a.name);
                                        agentStore.selectAgent(a.name);
                                    }}
                                />
                            ))}
                        </div>
                    </>
                )}

                {/* custom agents */}
                {customAgents.length > 0 && (
                    <>
                        <SectionTitle>Custom</SectionTitle>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                            {customAgents.map((a) => (
                                <AgentCard
                                    key={a.name}
                                    agent={a}
                                    onClick={() => {
                                        setSelected(a.name);
                                        agentStore.selectAgent(a.name);
                                    }}
                                />
                            ))}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
});

// ─── Agent detail (left tabs + right content) ───────────────────────────────

const AgentDetail = observer(function AgentDetail({ name, onBack }) {
    const { agentStore: s } = useStore();
    const [tab, setTab] = useState("prompt");

    if (s.loading || !s.current) return <Centered>Loading…</Centered>;

    const isBuiltin = s.current.is_builtin || false;

    return (
        <div className="flex h-full">
            {s.toast && <Toast {...s.toast} />}
            {/* left sidebar */}
            <div className="flex w-56 shrink-0 flex-col border-r border-border/60 bg-sidebar/20">
                <button
                    onClick={onBack}
                    className="flex items-center gap-1 px-4 py-3 text-sm text-muted-foreground transition hover:bg-foreground/5 hover:text-foreground"
                >
                    <ChevronLeft className="size-4" />
                    Agents
                </button>

                <div className="px-4 py-2">
                    <div className="flex items-center gap-2">
                        <Avatar seed={s.current.name} size={36} />
                        <div>
                            <div className="text-sm font-medium">
                                {s.current.name}
                            </div>
                            <code className="text-[10px] text-muted-foreground">
                                {s.current.name}
                            </code>
                        </div>
                    </div>
                </div>

                <div className="mt-2 flex flex-col gap-0.5 px-2">
                    <TabBtn
                        active={tab === "info"}
                        onClick={() => setTab("info")}
                        icon={<Bot className="size-3.5" />}
                    >
                        Info
                    </TabBtn>
                    <TabBtn
                        active={tab === "prompt"}
                        onClick={() => setTab("prompt")}
                        icon={<FileText className="size-3.5" />}
                    >
                        Prompt
                    </TabBtn>
                    <TabBtn
                        active={tab === "tools"}
                        onClick={() => setTab("tools")}
                        icon={<Wrench className="size-3.5" />}
                    >
                        Tools
                    </TabBtn>
                    <TabBtn
                        active={tab === "skills"}
                        onClick={() => setTab("skills")}
                        icon={<Sparkles className="size-3.5" />}
                    >
                        Skills
                    </TabBtn>
                    <TabBtn
                        active={tab === "subagents"}
                        onClick={() => setTab("subagents")}
                        icon={<Bot className="size-3.5" />}
                    >
                        SubAgents
                    </TabBtn>
                    <TabBtn
                        active={tab === "interrupt"}
                        onClick={() => setTab("interrupt")}
                        icon={<AlertCircle className="size-3.5" />}
                    >
                        Interrupt
                    </TabBtn>
                </div>

                <div className="mt-auto p-3">
                    {!isBuiltin && (
                        <button
                            onClick={() => s.save()}
                            disabled={s.saving}
                            className="flex w-full items-center justify-center gap-1.5 rounded-full bg-accent/15 px-3 py-2 text-[13px] text-accent transition hover:bg-accent/25 disabled:opacity-50"
                        >
                            <Save className="size-3.5" />
                            {s.saving ? "Saving…" : "Save"}
                        </button>
                    )}
                    {isBuiltin && (
                        <div className="flex items-center justify-center gap-1.5 px-3 py-2 text-[12px] text-muted-foreground/50">
                            <Lock className="size-3" />
                            Built-in (read-only)
                        </div>
                    )}
                </div>
            </div>

            {/* right content */}
            <div className="min-h-0 flex-1 overflow-hidden">
                <div className="flex h-full w-full flex-col px-8 py-8">
                    {tab === "info" && (
                        <div className="space-y-4">
                            <div>
                                <label className="mb-1 block text-[12px] font-medium text-muted-foreground">
                                    Name
                                </label>
                                <div className="rounded-lg border border-border/40 bg-sidebar/20 px-3 py-2 text-[13px] text-muted-foreground">
                                    {s.current.name}
                                </div>
                            </div>
                            <div>
                                <label className="mb-1 block text-[12px] font-medium text-muted-foreground">
                                    Description
                                </label>
                                <textarea
                                    value={s.descriptionDraft}
                                    onChange={(e) =>
                                        isBuiltin
                                            ? null
                                            : s.setDescriptionDraft(
                                                  e.target.value
                                              )
                                    }
                                    readOnly={isBuiltin}
                                    placeholder="Describe what this agent does and when to use it..."
                                    className="min-h-[80px] w-full resize-y rounded-lg border border-border/60 bg-sidebar/30 px-3 py-2 text-[13px] outline-none focus:border-accent/40"
                                />
                                <p className="mt-1 text-[11px] text-muted-foreground/60">
                                    Used by Manus/TeamLeader to decide when to
                                    dispatch to this agent.
                                </p>
                            </div>
                        </div>
                    )}

                    {tab === "prompt" && (
                        <div className="flex h-full flex-col">
                            <h2 className="mb-3 shrink-0 text-sm font-medium">
                                System Prompt
                            </h2>
                            <div className="min-h-0 flex-1">
                                <MDEditor
                                    value={s.promptDraft}
                                    onChange={
                                        isBuiltin
                                            ? undefined
                                            : (val) =>
                                                  s.setPromptDraft(val || "")
                                    }
                                    height="100%"
                                    preview="live"
                                    data-color-mode="dark"
                                    style={{ height: "100%" }}
                                    readOnly={isBuiltin}
                                />
                            </div>
                        </div>
                    )}

                    {tab === "tools" && (
                        <div>
                            <h2 className="mb-3 text-sm font-medium">
                                Tools Configuration
                            </h2>
                            <p className="mb-4 text-[12px] text-muted-foreground">
                                Select which tools this agent can use.
                            </p>
                            <div className="space-y-2">
                                {s.tools.map((tool) => {
                                    const checked = s.toolDraft.has(tool.name);
                                    return (
                                        <button
                                            key={tool.name}
                                            onClick={
                                                isBuiltin
                                                    ? undefined
                                                    : () =>
                                                          s.toggleTool(
                                                              tool.name
                                                          )
                                            }
                                            disabled={isBuiltin}
                                            className={cn(
                                                "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition",
                                                checked
                                                    ? "border-accent/30 bg-accent/5"
                                                    : "border-border/40",
                                                !isBuiltin &&
                                                    "hover:border-border/80",
                                                isBuiltin &&
                                                    "cursor-default opacity-60"
                                            )}
                                        >
                                            <div
                                                className={cn(
                                                    "flex size-5 shrink-0 items-center justify-center rounded border",
                                                    checked
                                                        ? "border-accent bg-accent"
                                                        : "border-border/60"
                                                )}
                                            >
                                                {checked && (
                                                    <Check className="size-3 text-accent-foreground" />
                                                )}
                                            </div>
                                            <div className="min-w-0 flex-1">
                                                <div className="flex items-center gap-1.5">
                                                    <span className="text-[13px] font-medium">
                                                        {tool.name}
                                                    </span>
                                                    <span
                                                        className={cn(
                                                            "rounded-sm px-1 py-0.5 text-[9px]",
                                                            tool.source ===
                                                                "user"
                                                                ? "bg-foreground/10 text-foreground/80"
                                                                : "bg-muted/20 text-muted-foreground"
                                                        )}
                                                    >
                                                        {tool.source}
                                                    </span>
                                                </div>
                                                <p className="truncate text-[11px] text-muted-foreground">
                                                    {tool.description}
                                                </p>
                                            </div>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {tab === "skills" && (
                        <div>
                            <h2 className="mb-3 text-sm font-medium">Skills</h2>
                            <p className="mb-4 text-[12px] text-muted-foreground">
                                Skills are loaded progressively by the agent
                                (SKILL.md + scripts). Select which skills this
                                agent can access.
                            </p>
                            {s.skills.length === 0 ? (
                                <p className="text-[12px] text-muted-foreground/60">
                                    No skills installed. Create skills in
                                    ~/.openmanus/skills/.
                                </p>
                            ) : (
                                <div className="space-y-2">
                                    {s.skills.map((skill) => {
                                        const checked = s.skillDraft.has(
                                            skill.name
                                        );
                                        return (
                                            <button
                                                key={skill.name}
                                                onClick={
                                                    isBuiltin
                                                        ? undefined
                                                        : () =>
                                                              s.toggleSkill(
                                                                  skill.name
                                                              )
                                                }
                                                disabled={isBuiltin}
                                                className={cn(
                                                    "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition",
                                                    checked
                                                        ? "border-accent/30 bg-accent/5"
                                                        : "border-border/40",
                                                    !isBuiltin &&
                                                        "hover:border-border/80",
                                                    isBuiltin &&
                                                        "cursor-default opacity-60"
                                                )}
                                            >
                                                <div
                                                    className={cn(
                                                        "flex size-5 shrink-0 items-center justify-center rounded border",
                                                        checked
                                                            ? "border-accent bg-accent"
                                                            : "border-border/60"
                                                    )}
                                                >
                                                    {checked && (
                                                        <Check className="size-3 text-accent-foreground" />
                                                    )}
                                                </div>
                                                <div className="min-w-0 flex-1">
                                                    <div className="flex items-center gap-1.5">
                                                        <span className="text-[13px] font-medium">
                                                            {skill.name}
                                                        </span>
                                                        {skill.has_scripts && (
                                                            <span className="rounded-sm bg-foreground/10 px-1 py-0.5 text-[9px] text-muted-foreground">
                                                                scripts
                                                            </span>
                                                        )}
                                                    </div>
                                                    <p className="truncate text-[11px] text-muted-foreground">
                                                        {skill.description}
                                                    </p>
                                                </div>
                                            </button>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    )}

                    {tab === "subagents" && (
                        <div>
                            <h2 className="mb-3 text-sm font-medium">
                                SubAgents
                            </h2>
                            <p className="text-[12px] text-muted-foreground">
                                Configure which agents this agent can dispatch
                                to. Coming soon.
                            </p>
                        </div>
                    )}

                    {tab === "interrupt" && (
                        <div>
                            <h2 className="mb-3 text-sm font-medium">
                                Human-in-the-Loop
                            </h2>
                            <p className="text-[12px] text-muted-foreground">
                                Configure which tools require human approval
                                before execution. Coming soon.
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
});

// ─── small components ───────────────────────────────────────────────────────

function AgentCard({ agent, onClick }) {
    return (
        <button
            onClick={onClick}
            className="rounded-card group p-6 text-left"
        >
            <div className="mb-4 flex items-center gap-3">
                <Avatar seed={agent.name} size={44} />
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1">
                        <span className="truncate font-display text-xl font-medium tracking-tight">
                            {agent.name}
                        </span>
                        {agent.is_builtin && (
                            <Lock className="size-3 shrink-0 text-muted-foreground/50" />
                        )}
                    </div>
                    <div className="mt-0.5 flex gap-1">
                        {agent.strip_file_tools && <Badge>no files</Badge>}
                    </div>
                </div>
            </div>
            {agent.description && (
                <p className="mb-3 line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">
                    {agent.description}
                </p>
            )}
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                {agent.tools.length > 0 ? (
                    <>
                        <Wrench className="size-2.5" />
                        <span className="truncate">
                            {agent.tools.join(", ")}
                        </span>
                    </>
                ) : (
                    <span>{agent.allowed_tools.length} file tools</span>
                )}
            </div>
        </button>
    );
}

function Header() {
    return (
        <div className="mb-6 flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-lg bg-foreground/5 ring-1 ring-border/60">
                <Bot className="size-4 text-foreground/70" />
            </span>
            <h1 className="h-display">Agents</h1>
        </div>
    );
}

function TabBtn({ active, onClick, icon, children }) {
    return (
        <button
            onClick={onClick}
            className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] transition",
                active
                    ? "bg-foreground/8 text-foreground font-medium"
                    : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
            )}
        >
            {icon}
            {children}
        </button>
    );
}

function Badge({ children, color }) {
    return (
        <span
            className={cn(
                "rounded-sm px-1.5 py-0.5 text-[9px]",
                color === "accent"
                    ? "bg-accent/15 text-accent"
                    : "bg-muted/30 text-muted-foreground"
            )}
        >
            {children}
        </span>
    );
}

// ─── Create new agent form ──────────────────────────────────────────────────

const CreateAgent = observer(function CreateAgent({ onBack, onCreated }) {
    const { agentStore: s } = useStore();
    const [tab, setTab] = useState("info");
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [prompt, setPrompt] = useState("");
    const [selectedTools, setSelectedTools] = useState(new Set());
    const [selectedSkills, setSelectedSkills] = useState(new Set());

    useEffect(() => {
        s.loadTools();
        s.loadSkills();
    }, [s]);

    const toggleTool = (toolName) => {
        setSelectedTools((prev) => {
            const next = new Set(prev);
            if (next.has(toolName)) next.delete(toolName);
            else next.add(toolName);
            return next;
        });
    };

    const toggleSkillItem = (skillName) => {
        setSelectedSkills((prev) => {
            const next = new Set(prev);
            if (next.has(skillName)) next.delete(skillName);
            else next.add(skillName);
            return next;
        });
    };

    const handleCreate = async () => {
        if (!name.trim()) return;
        const ok = await s.create(
            name.trim(),
            prompt,
            [...selectedTools],
            [...selectedSkills],
            description
        );
        if (ok) onCreated(name.trim());
    };

    return (
        <div className="flex h-full">
            {s.toast && <Toast {...s.toast} />}
            {/* left sidebar: tabs */}
            <div className="flex w-56 shrink-0 flex-col border-r border-border/60 bg-sidebar/20">
                <button
                    onClick={onBack}
                    className="flex items-center gap-1 px-4 py-3 text-sm text-muted-foreground transition hover:bg-foreground/5 hover:text-foreground"
                >
                    <ChevronLeft className="size-4" />
                    Agents
                </button>
                <div className="px-4 py-2">
                    <div className="text-sm font-medium text-muted-foreground">
                        New Agent
                    </div>
                </div>
                <div className="mt-2 flex flex-col gap-0.5 px-2">
                    <TabBtn
                        active={tab === "info"}
                        onClick={() => setTab("info")}
                        icon={<Bot className="size-3.5" />}
                    >
                        Info
                    </TabBtn>
                    <TabBtn
                        active={tab === "prompt"}
                        onClick={() => setTab("prompt")}
                        icon={<FileText className="size-3.5" />}
                    >
                        Prompt
                    </TabBtn>
                    <TabBtn
                        active={tab === "tools"}
                        onClick={() => setTab("tools")}
                        icon={<Wrench className="size-3.5" />}
                    >
                        Tools
                    </TabBtn>
                    <TabBtn
                        active={tab === "skills"}
                        onClick={() => setTab("skills")}
                        icon={<Sparkles className="size-3.5" />}
                    >
                        Skills
                    </TabBtn>
                    <TabBtn
                        active={tab === "subagents"}
                        onClick={() => setTab("subagents")}
                        icon={<Bot className="size-3.5" />}
                    >
                        SubAgents
                    </TabBtn>
                    <TabBtn
                        active={tab === "interrupt"}
                        onClick={() => setTab("interrupt")}
                        icon={<AlertCircle className="size-3.5" />}
                    >
                        Interrupt
                    </TabBtn>
                </div>
                <div className="mt-auto p-3">
                    <button
                        onClick={handleCreate}
                        disabled={!name.trim() || s.saving}
                        className="flex w-full items-center justify-center gap-1.5 rounded-full bg-accent/15 px-3 py-2 text-[13px] text-accent transition hover:bg-accent/25 disabled:opacity-50"
                    >
                        <Save className="size-3.5" />
                        {s.saving ? "Creating…" : "Create"}
                    </button>
                </div>
            </div>

            {/* right content */}
            <div className="min-h-0 flex-1 overflow-hidden">
                <div className="flex h-full w-full flex-col px-8 py-8">
                    {tab === "info" && (
                        <div className="space-y-4">
                            <h2 className="text-sm font-medium">Agent Info</h2>
                            <div>
                                <label className="mb-1 block text-[12px] font-medium text-muted-foreground">
                                    Name
                                </label>
                                <input
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    placeholder="e.g. code_reviewer"
                                    className="w-full rounded-lg border border-border/60 bg-sidebar/30 px-3 py-2 text-[13px] outline-none focus:border-accent/40"
                                />
                                <p className="mt-1 text-[11px] text-muted-foreground/60">
                                    Unique agent identifier. Cannot be changed
                                    after creation.
                                </p>
                            </div>
                            <div>
                                <label className="mb-1 block text-[12px] font-medium text-muted-foreground">
                                    Description
                                </label>
                                <textarea
                                    value={description}
                                    onChange={(e) =>
                                        setDescription(e.target.value)
                                    }
                                    placeholder="Describe what this agent does and when to use it..."
                                    className="min-h-[80px] w-full resize-y rounded-lg border border-border/60 bg-sidebar/30 px-3 py-2 text-[13px] outline-none focus:border-accent/40"
                                />
                                <p className="mt-1 text-[11px] text-muted-foreground/60">
                                    Used by Manus/TeamLeader to decide when to
                                    dispatch to this agent.
                                </p>
                            </div>
                        </div>
                    )}

                    {tab === "prompt" && (
                        <div className="flex h-full flex-col">
                            <h2 className="mb-3 shrink-0 text-sm font-medium">
                                System Prompt
                            </h2>
                            <div className="min-h-0 flex-1">
                                <MDEditor
                                    value={prompt}
                                    onChange={(val) => setPrompt(val || "")}
                                    height="100%"
                                    preview="live"
                                    data-color-mode="dark"
                                    style={{ height: "100%" }}
                                />
                            </div>
                        </div>
                    )}

                    {tab === "tools" && (
                        <div>
                            <h2 className="mb-3 text-sm font-medium">Tools</h2>
                            <p className="mb-4 text-[12px] text-muted-foreground">
                                Select tools for this agent. Create or import
                                new tools in the Tools page.
                            </p>
                            <div className="space-y-2">
                                {s.tools.map((tool) => {
                                    const checked = selectedTools.has(
                                        tool.name
                                    );
                                    return (
                                        <button
                                            key={tool.name}
                                            onClick={() =>
                                                toggleTool(tool.name)
                                            }
                                            className={cn(
                                                "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition",
                                                checked
                                                    ? "border-accent/30 bg-accent/5"
                                                    : "border-border/40 hover:border-border/80"
                                            )}
                                        >
                                            <div
                                                className={cn(
                                                    "flex size-5 shrink-0 items-center justify-center rounded border",
                                                    checked
                                                        ? "border-accent bg-accent"
                                                        : "border-border/60"
                                                )}
                                            >
                                                {checked && (
                                                    <Check className="size-3 text-accent-foreground" />
                                                )}
                                            </div>
                                            <div className="min-w-0 flex-1">
                                                <div className="flex items-center gap-1.5">
                                                    <span className="text-[13px] font-medium">
                                                        {tool.name}
                                                    </span>
                                                    <span
                                                        className={cn(
                                                            "rounded-sm px-1 py-0.5 text-[9px]",
                                                            tool.source ===
                                                                "user"
                                                                ? "bg-foreground/10 text-foreground/80"
                                                                : "bg-muted/20 text-muted-foreground"
                                                        )}
                                                    >
                                                        {tool.source}
                                                    </span>
                                                </div>
                                                <p className="truncate text-[11px] text-muted-foreground">
                                                    {tool.description}
                                                </p>
                                            </div>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {tab === "skills" && (
                        <div>
                            <h2 className="mb-3 text-sm font-medium">Skills</h2>
                            <p className="mb-4 text-[12px] text-muted-foreground">
                                Select skills for this agent.
                            </p>
                            {s.skills.length === 0 ? (
                                <p className="text-[12px] text-muted-foreground/60">
                                    No skills installed in ~/.openmanus/skills/.
                                </p>
                            ) : (
                                <div className="space-y-2">
                                    {s.skills.map((skill) => {
                                        const checked = selectedSkills.has(
                                            skill.name
                                        );
                                        return (
                                            <button
                                                key={skill.name}
                                                onClick={() =>
                                                    toggleSkillItem(skill.name)
                                                }
                                                className={cn(
                                                    "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition",
                                                    checked
                                                        ? "border-accent/30 bg-accent/5"
                                                        : "border-border/40 hover:border-border/80"
                                                )}
                                            >
                                                <div
                                                    className={cn(
                                                        "flex size-5 shrink-0 items-center justify-center rounded border",
                                                        checked
                                                            ? "border-accent bg-accent"
                                                            : "border-border/60"
                                                    )}
                                                >
                                                    {checked && (
                                                        <Check className="size-3 text-accent-foreground" />
                                                    )}
                                                </div>
                                                <div className="min-w-0 flex-1">
                                                    <span className="text-[13px] font-medium">
                                                        {skill.name}
                                                    </span>
                                                    <p className="truncate text-[11px] text-muted-foreground">
                                                        {skill.description}
                                                    </p>
                                                </div>
                                            </button>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    )}

                    {tab === "subagents" && (
                        <div>
                            <h2 className="mb-3 text-sm font-medium">
                                SubAgents
                            </h2>
                            <p className="text-[12px] text-muted-foreground">
                                Configure which agents this agent can dispatch
                                to. Coming soon.
                            </p>
                        </div>
                    )}

                    {tab === "interrupt" && (
                        <div>
                            <h2 className="mb-3 text-sm font-medium">
                                Human-in-the-Loop
                            </h2>
                            <p className="text-[12px] text-muted-foreground">
                                Configure which tools require human approval
                                before execution. Coming soon.
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
});

function Centered({ children }) {
    return (
        <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">{children}</p>
        </div>
    );
}

function SectionTitle({ children }) {
    return (
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.15em] text-foreground/45">
            {children}
        </div>
    );
}

function Toast({ type, message }) {
    return (
        <div
            className={cn(
                "fixed right-4 top-14 z-50 flex items-center gap-2 rounded-full px-4 py-2.5 text-[13px] shadow-lg anim-rise",
                type === "error"
                    ? "bg-destructive/15 text-destructive"
                    : "bg-accent/15 text-accent accent-glow"
            )}
        >
            {type === "error" ? (
                <AlertCircle className="size-3.5" />
            ) : (
                <Check className="size-3.5" />
            )}
            {message}
        </div>
    );
}
