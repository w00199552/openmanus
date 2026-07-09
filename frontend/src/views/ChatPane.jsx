import {observer} from "mobx-react-lite";
import {useEffect} from "react";

import {useStore} from "@/hooks/useStore";
import {ThreadView} from "@/components/chat/ThreadView";
import {ChatInput} from "@/components/chat/ChatInput";
import {TooltipProvider} from "@/components/ui/tooltip";

/**
 * ChatPane — the middle column, driven by the multi-agent runtime.
 *
 * One unified view: the runtime's `activeMessages` is either a single session's
 * messages (1:1) or the team's merged timeline (group chat). Switching the
 * active session rebinds the runtime's live subscription; the runtime owns all
 * streaming state, this component just reads observables + forwards actions.
 */
export const ChatPane = observer(function ChatPane() {
  const { sessions, runtime } = useStore();
  const active = sessions.active;
  const sessionId = active?.id;
  const isTeam = active?.kind === "team";
  // team session → scope view (fan-in); single session → scope null
  const scopeId = isTeam ? sessionId : null;

  // When the active session/scope changes, tell the runtime to switch what it's
  // observing (it loads history + rebuilds the SSE subscription).
  useEffect(() => {
    if (sessionId) runtime.setActive(sessionId, scopeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, scopeId]);

  /** "New chat" = reset the default entry's history. */
  const handleNewChat = async () => {
    await sessions.resetDefault();
    runtime.clear("manus");
  };

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-full flex-col bg-background">
        {/* header strip */}
        <div className="flex items-center gap-2 border-b border-border/60 px-5 py-2.5">
          <span
            className={
              isTeam
                ? "size-1.5 rounded-full bg-accent"
                : "size-1.5 rounded-full bg-muted-foreground/40"
            }
          />
          <span className="truncate text-[13px] font-medium">
            {active
              ? active.kind === "subagent"
                ? active.name || "agent"
                : active.kind === "team"
                  ? "Team"
                  : active.title || active.id.slice(0, 12)
              : "New conversation"}
          </span>
          {isTeam && (
            <span className="rounded-sm bg-accent/10 px-1.5 text-[10px] text-accent">
              team
            </span>
          )}
          <span className="ml-auto text-[11px] text-muted-foreground">
            {runtime.isRunning ? "thinking…" : "1:1"}
          </span>
        </div>

        {/* messages: the runtime's activeMessages (single session or team merge) */}
        <div className="min-h-0 flex-1">
          <ThreadView messages={runtime.activeMessages} session={active} />
        </div>

        {/* input: reuse the existing ChatInput, wired to the runtime */}
        <ChatInput
          onSend={(text) => runtime.send(sessionId, text)}
          onStop={() => runtime.stop(sessionId)}
          isLoading={runtime.isRunning}
          showNewChat={active?.kind === "root"}
          onNewChat={handleNewChat}
        />
      </div>
    </TooltipProvider>
  );
});
