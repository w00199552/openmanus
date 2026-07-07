import { useEffect, useState } from "react";
import {
  Bot, Wrench, Sparkles, ChevronLeft, Check, FileText,
} from "lucide-react";

import { listAgents, getAgent, listTools } from "@/services/agentService";
import { cn } from "@/lib/utils";

/**
 * AgentsView — card grid of agents; click a card to open its config page.
 *
 * Config page shows: display_name, system prompt, and a tool checklist
 * (all available tools with checkboxes for what this agent has).
 */
export function AgentsView() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null); // agent name for detail view

  const reload = () => {
    setLoading(true);
    listAgents()
      .then((data) => { setAgents(data); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  };

  useEffect(() => { reload(); }, []);

  if (loading) return <Centered>Loading agents…</Centered>;
  if (error) return <Centered className="text-destructive">{error}</Centered>;

  // Detail view
  if (selected) {
    return (
      <AgentDetail
        name={selected}
        onBack={() => { setSelected(null); reload(); }}
      />
    );
  }

  // Card grid
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="mb-6 flex items-center gap-2">
          <Bot className="size-5 text-accent" />
          <h1 className="text-lg font-semibold">Agents</h1>
          <span className="text-sm text-muted-foreground">({agents.length})</span>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <button
              key={agent.name}
              onClick={() => setSelected(agent.name)}
              className="group rounded-xl border border-border/60 bg-card p-4 text-left transition hover:border-accent/40 hover:bg-sidebar/30"
            >
              <div className="mb-3 flex items-center gap-3">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent/10">
                  <Bot className="size-5 text-accent" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-sm font-medium">{agent.display_name}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1 mt-0.5">
                    {agent.is_entry && (
                      <span className="rounded-sm bg-accent/15 px-1.5 py-0.5 text-[9px] text-accent">entry</span>
                    )}
                    {agent.strip_file_tools && (
                      <span className="rounded-sm bg-muted/30 px-1.5 py-0.5 text-[9px] text-muted-foreground">no files</span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                {agent.tools.length > 0 ? (
                  <>
                    <Wrench className="size-2.5" />
                    <span className="truncate">{agent.tools.join(", ")}</span>
                  </>
                ) : (
                  <span>{agent.allowed_tools.length} file tools</span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Agent detail / config page. */
function AgentDetail({ name, onBack }) {
  const [agent, setAgent] = useState(null);
  const [tools, setTools] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getAgent(name), listTools()])
      .then(([a, t]) => {
        setAgent(a);
        setTools(t);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [name]);

  if (loading) return <Centered>Loading…</Centered>;
  if (!agent) return <Centered>Agent not found</Centered>;

  const agentTools = new Set(agent.tools || []);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-8">
        {/* back */}
        <button
          onClick={onBack}
          className="mb-4 flex items-center gap-1 text-sm text-muted-foreground transition hover:text-foreground"
        >
          <ChevronLeft className="size-4" />
          Back
        </button>

        {/* header */}
        <div className="mb-6 flex items-center gap-3">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-accent/10">
            <Bot className="size-6 text-accent" />
          </div>
          <div>
            <h1 className="text-xl font-semibold">{agent.display_name}</h1>
            <div className="mt-0.5 flex items-center gap-1.5">
              <code className="text-[11px] text-muted-foreground">{agent.name}</code>
              {agent.is_entry && (
                <span className="rounded-sm bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent">entry</span>
              )}
              {agent.strip_file_tools && (
                <span className="rounded-sm bg-muted/30 px-1.5 py-0.5 text-[10px] text-muted-foreground">no files</span>
              )}
            </div>
          </div>
        </div>

        {/* system prompt */}
        <Section title="System Prompt" icon={<FileText className="size-3.5" />}>
          <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap rounded-lg bg-sidebar/30 px-4 py-3 font-mono text-[12px] leading-relaxed text-muted-foreground/80">
            {agent.prompt || "(empty)"}
          </pre>
        </Section>

        {/* tools */}
        <Section title="Tools" icon={<Wrench className="size-3.5" />}>
          <div className="space-y-1.5">
            {tools.map((tool) => {
              const checked = agentTools.has(tool.name);
              return (
                <div
                  key={tool.name}
                  className={cn(
                    "flex items-center gap-3 rounded-lg border px-3 py-2",
                    checked ? "border-accent/30 bg-accent/5" : "border-border/40",
                  )}
                >
                  <div
                    className={cn(
                      "flex size-5 shrink-0 items-center justify-center rounded border",
                      checked ? "border-accent bg-accent text-accent-foreground" : "border-border/60",
                    )}
                  >
                    {checked && <Check className="size-3" />}
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
                </div>
              );
            })}
          </div>
        </Section>

        {/* file tools (allowed_tools) */}
        {agent.allowed_tools && agent.allowed_tools.length > 0 && (
          <Section title="File Tools (from backend)" icon={<Wrench className="size-3.5" />}>
            <div className="flex flex-wrap gap-1.5">
              {agent.allowed_tools.map((t) => (
                <span key={t} className="rounded-md bg-muted/20 px-2 py-1 text-[11px] text-muted-foreground">
                  {t}
                </span>
              ))}
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}

// ─── small helpers ──────────────────────────────────────────────────────────

function Centered({ children, className }) {
  return (
    <div className={cn("flex h-full items-center justify-center", className)}>
      <p className="text-sm">{children}</p>
    </div>
  );
}

function Section({ title, icon, children }) {
  return (
    <div className="mb-6">
      <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
        {icon}
        {title}
      </div>
      {children}
    </div>
  );
}
