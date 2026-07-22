import { observer } from "mobx-react-lite";
import { useEffect, useState } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

import { useStore } from "@/hooks/use-store";
import { ThreadView } from "@/components/chat/thread-view";
import { ChatInput } from "@/components/chat/chat-input";
import { TooltipProvider } from "@/components/ui/tooltip";

/**
 * ChatPane — the middle column, driven by the multi-agent runtime.
 *
 * One unified view: the runtime's `activeMessages` is either a single session's
 * messages (1:1) or the team's merged timeline (group chat). Switching the
 * active session rebinds the runtime's live subscription; the runtime owns all
 * streaming state, this component just reads observables + forwards actions.
 */
export const ChatPane = observer(function ChatPane({ onToggleCollapse }) {
    const { sessions, runtime } = useStore();
    const active = sessions.active;
    const sessionId = active?.id;
    const isTeam = active?.kind === "team";
    // team session → topic view (fan-in); single session → topic null
    const topicId = isTeam ? active?.topic_id : null;

    // When the active session/topic changes, tell the runtime to switch what it's
    // observing (it loads history + rebuilds the SSE subscription).
    useEffect(() => {
        if (sessionId) runtime.setActive(sessionId, topicId);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sessionId, topicId]);

    /** "New chat" = reset the default entry's history. */
    const handleNewChat = async () => {
        await sessions.resetDefault();
        runtime.clear("manus");
    };

    return (
        <TooltipProvider delayDuration={300}>
            <div className="flex h-full flex-col bg-background">
                {/* header strip */}
                <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border/60 px-5">
                    <span
                        className={
                            isTeam
                                ? "size-1.5 rounded-full bg-foreground/50"
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
                        <span className="rounded-sm bg-foreground/8 px-1.5 text-[10px] text-muted-foreground">
                            team
                        </span>
                    )}
                    <span className="ml-auto text-[11px] text-muted-foreground">
                        {runtime.isRunning ? "thinking…" : "1:1"}
                    </span>
                    <button
                        onClick={() => onToggleCollapse?.()}
                        className="ml-1 rounded-md p-1 text-muted-foreground transition hover:bg-card hover:text-foreground"
                        title="Collapse chat"
                    >
                        <PanelRightClose className="size-3.5" />
                    </button>
                </div>

                {/* messages: the runtime's activeMessages (single session or team merge) */}
                <div className="min-h-0 flex-1">
                    <ThreadView
                        messages={runtime.activeMessages}
                        session={active}
                    />
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
