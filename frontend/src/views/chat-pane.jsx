import { observer } from "mobx-react-lite";
import { useEffect } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";

import { useStore } from "@/hooks/use-store";
import { resetHistory } from "@/services/session-service";
import { ThreadView } from "@/components/chat/thread-view";
import { ChatInput } from "@/components/chat/chat-input";
import { TooltipProvider } from "@/components/ui/tooltip";

/**
 * ChatPane — the middle column, driven by the multi-agent runtime.
 *
 * One unified view: the runtime's `activeMessages` is the active topic's
 * merged timeline (the backend fans in all member sessions of the topic on
 * the stream). Switching the active topic rebinds the runtime's live
 * subscription; the runtime owns all streaming state, this component just
 * reads observables + forwards actions.
 */
export const ChatPane = observer(function ChatPane({ onToggleCollapse }) {
    const { topics, runtime } = useStore();
    const active = topics.active;
    const topicId = active?.id;
    const isTeam = active?.kind === "team";

    // Every topic (single-agent or team) subscribes via ?topic= fan-in.
    // A single-agent topic is just a team of one — same code path, no branching.
    useEffect(() => {
        if (topicId) runtime.setActive(topicId);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [topicId]);

    /** "New chat" = reset the main topic's history. */
    const handleNewChat = async () => {
        await resetHistory("manus").catch(() => {});
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
                                ? active.agent_name || "agent"
                                : active.kind === "team"
                                  ? "Team"
                                  : active.title || (active.id || "").slice(0, 12)
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
                    onSend={(text) => runtime.send(topicId, text)}
                    onStop={() => runtime.stop(topicId)}
                    isLoading={runtime.isRunning}
                    showNewChat={active?.kind === "root"}
                    onNewChat={handleNewChat}
                />
            </div>
        </TooltipProvider>
    );
});
