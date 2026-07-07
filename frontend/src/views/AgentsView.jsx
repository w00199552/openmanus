import { useEffect, useState, useCallback } from "react";
import {
  Bot, Wrench, FileText, ChevronLeft, Check, Sparkles, Save,
} from "lucide-react";

import { listAgents, getAgent, listTools } from "@/services/agentService";
import { cn } from "@/lib/utils";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

/**
 * AgentsView — card grid → click to open config (left tabs: Prompt / Tools).
 */
export function AgentsView() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);

  const reload = useCallback(() => {
    listAgents().then(setAgents).finally(() => setLoading(false));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  if (loading) return <Centered>Loading…</Centered>;

  if (selected) {
    return <AgentDetail name={selected} onBack={() => { setSelected(null); reload(); }} />;
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <Header />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((a) => (
            <AgentCard key={a.name} agent={a} onClick={() => setSelected(a.name)} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Agent detail (left tabs + right content) ───────────────────────────────

function AgentDetail({ name, onBack }) {
  const [agent, setAgent] = useState(null);
  const [tools, setTools] = useState([]);
  const [tab, setTab] = useState("prompt");
  const [loading, setLoading] = useState(true);
  // edit state
  const [promptDraft, setPromptDraft] = useState("");
  const [toolDraft, setToolDraft] = useState(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([getAgent(name), listTools()])
      .then(([a, t]) => {
        setAgent(a);
        setTools(t);
        setPromptDraft(a.prompt || "");
        setToolDraft(new Set(a.tools || []));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [name]);

  const toggleTool = (toolName) => {
    setToolDraft((prev) => {
      const next = new Set(prev);
      if (next.has(toolName)) next.delete(toolName);
      else next.add(toolName);
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    try {
      await fetch(`${BACKEND}/agents/${encodeURIComponent(name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptDraft, tools: [...toolDraft] }),
      });
      // reload agent
      const updated = await getAgent(name);
      setAgent(updated);
      setPromptDraft(updated.prompt || "");
      setToolDraft(new Set(updated.tools || []));
    } catch { /* ignore */ }
    setSaving(false);
  };

  if (loading || !agent) return <Centered>Loading…</Centered>;

  return (
    <div className="flex h-full">
      {/* left sidebar: back + agent info + vertical tabs */}
      <div className="flex w-56 shrink-0 flex-col border-r border-border/60 bg-sidebar/20">
        <button
          onClick={onBack}
          className="flex items-center gap-1 px-4 py-3 text-sm text-muted-foreground transition hover:text-foreground"
        >
          <ChevronLeft className="size-4" />
          Agents
        </button>

        <div className="px-4 py-2">
          <div className="flex items-center gap-2">
            <div className="flex size-9 items-center justify-center rounded-lg bg-accent/10">
              <Bot className="size-4.5 text-accent" />
            </div>
            <div>
              <div className="text-sm font-medium">{agent.display_name}</div>
              <code className="text-[10px] text-muted-foreground">{agent.name}</code>
            </div>
          </div>
        </div>

        <div className="mt-2 flex flex-col gap-0.5 px-2">
          <TabBtn active={tab === "prompt"} onClick={() => setTab("prompt")} icon={<FileText className="size-3.5" />}>
            Prompt
          </TabBtn>
          <TabBtn active={tab === "tools"} onClick={() => setTab("tools")} icon={<Wrench className="size-3.5" />}>
            Tools
          </TabBtn>
          <TabBtn active={tab === "skills"} onClick={() => setTab("skills")} icon={<Sparkles className="size-3.5" />}>
            Skills
          </TabBtn>
        </div>

        <div className="mt-auto p-3">
          <button
            onClick={save}
            disabled={saving}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent/15 px-3 py-2 text-[13px] text-accent transition hover:bg-accent/25 disabled:opacity-50"
          >
            <Save className="size-3.5" />
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* right content */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl px-6 py-6">
          {tab === "prompt" && (
            <div>
              <h2 className="mb-3 text-sm font-medium">System Prompt</h2>
              <textarea
                value={promptDraft}
                onChange={(e) => setPromptDraft(e.target.value)}
                className="min-h-[400px] w-full resize-y rounded-lg border border-border/60 bg-sidebar/30 px-4 py-3 font-mono text-[13px] leading-relaxed text-foreground/90 outline-none focus:border-accent/40"
                placeholder="Write the system prompt..."
              />
            </div>
          )}

          {tab === "tools" && (
            <div>
              <h2 className="mb-3 text-sm font-medium">Tools Configuration</h2>
              <p className="mb-4 text-[12px] text-muted-foreground">
                Select which tools this agent can use. Built-in tools are provided by the platform; user tools come from ~/.openmanus/tools/.
              </p>
              <div className="space-y-1.5">
                {tools.map((tool) => {
                  const checked = toolDraft.has(tool.name);
                  return (
                    <button
                      key={tool.name}
                      onClick={() => toggleTool(tool.name)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition",
                        checked ? "border-accent/30 bg-accent/5" : "border-border/40 hover:border-border/80",
                      )}
                    >
                      <div className={cn(
                        "flex size-5 shrink-0 items-center justify-center rounded border",
                        checked ? "border-accent bg-accent" : "border-border/60",
                      )}>
                        {checked && <Check className="size-3 text-accent-foreground" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="text-[13px] font-medium">{tool.name}</span>
                          <span className={cn(
                            "rounded-sm px-1 py-0.5 text-[9px]",
                            tool.source === "user" ? "bg-accent/10 text-accent" : "bg-muted/20 text-muted-foreground",
                          )}>
                            {tool.source}
                          </span>
                        </div>
                        <p className="truncate text-[11px] text-muted-foreground">{tool.description}</p>
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
              <p className="text-[12px] text-muted-foreground">
                Skills are file bundles (Claude Code style). Coming soon.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── small components ───────────────────────────────────────────────────────

function AgentCard({ agent, onClick }) {
  return (
    <button
      onClick={onClick}
      className="group rounded-xl border border-border/60 bg-card p-4 text-left transition hover:border-accent/40 hover:bg-sidebar/30"
    >
      <div className="mb-3 flex items-center gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent/10">
          <Bot className="size-5 text-accent" />
        </div>
        <div className="min-w-0">
          <span className="truncate text-sm font-medium">{agent.display_name}</span>
          <div className="mt-0.5 flex gap-1">
            {agent.is_entry && <Badge color="accent">entry</Badge>}
            {agent.strip_file_tools && <Badge>no files</Badge>}
          </div>
        </div>
      </div>
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        {agent.tools.length > 0 ? (
          <><Wrench className="size-2.5" /><span className="truncate">{agent.tools.join(", ")}</span></>
        ) : (
          <span>{agent.allowed_tools.length} file tools</span>
        )}
      </div>
    </button>
  );
}

function Header() {
  return (
    <div className="mb-6 flex items-center gap-2">
      <Bot className="size-5 text-accent" />
      <h1 className="text-lg font-semibold">Agents</h1>
    </div>
  );
}

function TabBtn({ active, onClick, icon, children }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] transition",
        active ? "bg-accent/10 text-accent font-medium" : "text-muted-foreground hover:text-foreground hover:bg-sidebar/40",
      )}
    >
      {icon}
      {children}
    </button>
  );
}

function Badge({ children, color }) {
  return (
    <span className={cn(
      "rounded-sm px-1.5 py-0.5 text-[9px]",
      color === "accent" ? "bg-accent/15 text-accent" : "bg-muted/30 text-muted-foreground",
    )}>
      {children}
    </span>
  );
}

function Centered({ children }) {
  return <div className="flex h-full items-center justify-center"><p className="text-sm text-muted-foreground">{children}</p></div>;
}
