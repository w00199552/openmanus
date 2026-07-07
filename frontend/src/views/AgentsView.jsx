import { useEffect, useState } from "react";
import { Bot, Wrench, Sparkles, ChevronRight, ChevronDown } from "lucide-react";

import { listAgents, getAgent } from "@/services/agentService";
import { cn } from "@/lib/utils";

/**
 * AgentsView — displays all agent configurations from ~/.openmanus/agents/.
 *
 * Shows a card per agent with: name, role badge (entry/dispatchable), tools,
 * and a collapsible system prompt preview.
 */
export function AgentsView() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null); // agent name being expanded
  const [promptText, setPromptText] = useState("");

  useEffect(() => {
    listAgents()
      .then((data) => {
        setAgents(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  const toggleExpand = async (name) => {
    if (expanded === name) {
      setExpanded(null);
      return;
    }
    setExpanded(name);
    setPromptText("");
    try {
      const detail = await getAgent(name);
      setPromptText(detail.prompt || "(empty)");
    } catch {
      setPromptText("(failed to load)");
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading agents…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-6 py-8">
        <div className="mb-6 flex items-center gap-2">
          <Bot className="size-5 text-accent" />
          <h1 className="text-lg font-semibold">Agents</h1>
          <span className="text-sm text-muted-foreground">
            ({agents.length})
          </span>
        </div>

        <div className="space-y-3">
          {agents.map((agent) => (
            <div
              key={agent.name}
              className="rounded-lg border border-border/60 bg-card overflow-hidden"
            >
              {/* header row */}
              <button
                onClick={() => toggleExpand(agent.name)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-sidebar/40"
              >
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent/10">
                  <Bot className="size-4 text-accent" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{agent.display_name}</span>
                    {agent.is_entry && (
                      <span className="rounded-sm bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent">
                        entry
                      </span>
                    )}
                    {agent.strip_file_tools && (
                      <span className="rounded-sm bg-muted/30 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        no files
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    {agent.tools.length > 0 ? (
                      <>
                        <Wrench className="size-2.5" />
                        <span>{agent.tools.join(", ")}</span>
                      </>
                    ) : (
                      <span>{agent.allowed_tools.length} file tools</span>
                    )}
                  </div>
                </div>
                {expanded === agent.name ? (
                  <ChevronDown className="size-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="size-4 text-muted-foreground" />
                )}
              </button>

              {/* expanded: prompt preview */}
              {expanded === agent.name && (
                <div className="border-t border-border/60 px-4 py-3">
                  <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                    <Sparkles className="size-3" />
                    System Prompt
                  </div>
                  <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap rounded-md bg-sidebar/30 px-3 py-2 font-mono text-[12px] leading-relaxed text-muted-foreground/80">
                    {promptText}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
