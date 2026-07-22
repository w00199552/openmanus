import { observer } from "mobx-react-lite";
import { useEffect, useState } from "react";
import { Search, Trash2 } from "lucide-react";

import { useStore } from "@/hooks/use-store";
import { SessionAvatar } from "@/components/avatar";
import { formatListTime } from "@/utils/time";
import { cn } from "@/lib/utils";

/**
 * TopicList — left rail, shows topics (task/conversation groups).
 *
 * Each row is a 2-line card:
 *   ┌─────────────────────────────────────┐
 *   │ [avatar]  title            12:30 ●  │  ← title + time + status
 *   │           preview text…     ⟳       │  ← last message preview + running
 *   └─────────────────────────────────────┘
 *
 * main topic is always pinned at top (Default group).
 * Task topics (dispatched work) are in the Tasks group below.
 */
export const TopicList = observer(function TopicList({
    collapsed = false,
}) {
    const { topics } = useStore();
    const [query, setQuery] = useState("");

    useEffect(() => {
        topics.load();
    }, [topics]);

    // Collapsed mode: narrow strip showing only avatars
    if (collapsed) {
        const all = [...topics.mainTopic, ...topics.taskTopics];
        return (
            <div className="flex h-full flex-col items-center gap-1 overflow-y-auto bg-card py-3">
                {all.map((t) => (
                    <button
                        key={t.id}
                        onClick={() => topics.select(t.id)}
                        className="relative shrink-0 rounded-lg p-1 transition hover:bg-sidebar/40"
                        title={t.title || t.agent_name || t.id.slice(0, 12)}
                    >
                        <TopicAvatar topic={t} size={32} />
                        {t.id === topics.activeTopicId && (
                            <span className="absolute -left-0.5 top-1/2 h-6 w-1 -translate-y-1/2 rounded-full bg-accent" />
                        )}
                        {topics.unreadCount(t.id) > 0 && (
                            <span className="absolute -right-0.5 -top-0.5 size-3.5 rounded-full bg-destructive text-[8px] font-bold text-white flex items-center justify-center">
                                {topics.unreadCount(t.id)}
                            </span>
                        )}
                    </button>
                ))}
            </div>
        );
    }

    // filter both groups by the search query (title + preview)
    const match = (t) => {
        if (!query.trim()) return true;
        const q = query.trim().toLowerCase();
        return (
            (t.title || "").toLowerCase().includes(q) ||
            (t.preview || "").toLowerCase().includes(q)
        );
    };
    const main = topics.mainTopic.filter(match);
    const tasks = topics.taskTopics.filter(match);

    return (
        <div className="flex h-full flex-col bg-card">
            {/* search */}
            <div className="px-2.5 pb-2 pt-3">
                <div className="flex items-center gap-1.5 rounded-full border border-border/60 bg-background/50 px-3 py-1.5 transition focus-within:border-accent/40 focus-within:shadow-[0_0_0_3px_hsl(var(--accent)/0.12)]">
                    <Search className="size-3.5 shrink-0 text-muted-foreground/60" />
                    <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search conversations"
                        className="w-full bg-transparent text-[12px] text-foreground outline-none placeholder:text-muted-foreground/50"
                    />
                </div>
            </div>

            {/* list */}
            <div className="flex-1 overflow-y-auto px-1.5 pb-3">
                {topics.loading && (
                    <p className="px-2.5 py-3 text-xs text-muted-foreground">
                        Loading…
                    </p>
                )}
                {topics.error && (
                    <p className="px-2.5 py-2 text-xs text-destructive">
                        {topics.error}
                    </p>
                )}

                {!topics.loading && (
                    <>
                        {/* DEFAULT group — main topic */}
                        <Section
                            title="Main"
                            empty={main.length === 0}
                            emptyHint={query.trim() ? "No matches." : undefined}
                        >
                            <ul className="space-y-1">
                                {main.map((t) => (
                                    <TopicItem
                                        key={t.id}
                                        topic={t}
                                        unread={topics.unreadCount(t.id)}
                                        active={t.id === topics.activeTopicId}
                                        onSelect={() => topics.select(t.id)}
                                    />
                                ))}
                            </ul>
                        </Section>

                        {/* TASKS group — dispatched work */}
                        <Section
                            title="Tasks"
                            empty={tasks.length === 0}
                            emptyHint={
                                query.trim() ? "No matches." : "No tasks yet."
                            }
                        >
                            <ul className="space-y-1">
                                {tasks.map((t) => (
                                    <TopicItem
                                        key={t.id}
                                        topic={t}
                                        unread={topics.unreadCount(t.id)}
                                        active={t.id === topics.activeTopicId}
                                        onSelect={() => topics.select(t.id)}
                                    />
                                ))}
                            </ul>
                        </Section>
                    </>
                )}
            </div>
        </div>
    );
});

/** A titled group section. */
function Section({ title, children, empty, emptyHint }) {
    if (empty && !emptyHint) return null;
    return (
        <div className="mb-1">
            <h3 className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                {title}
            </h3>
            {empty ? (
                <p className="px-2.5 pb-2 text-[11px] text-muted-foreground/50">
                    {emptyHint}
                </p>
            ) : (
                children
            )}
        </div>
    );
}

function TopicItem({ topic, unread, active, onSelect }) {
    const isRunning = topic.status === "running";
    const preview = topic.preview || "";

    return (
        <li>
            <button
                onClick={onSelect}
                className={cn(
                    "group relative flex w-full items-start gap-2.5 rounded-md px-2 py-2.5 text-left transition",
                    active
                        ? "bg-sidebar text-foreground"
                        : "text-muted-foreground hover:bg-sidebar/50 hover:text-foreground/80"
                )}
            >
                {active && (
                    <span className="absolute left-0 top-1/2 h-7 w-[2px] -translate-y-1/2 rounded-full bg-accent accent-glow" />
                )}

                <div className="relative mt-0.5">
                    <TopicAvatar topic={topic} size={36} />
                    {isRunning && (
                        <span className="absolute -bottom-0.5 -right-0.5 size-3 rounded-full bg-accent ring-2 ring-card animate-pulse-dot" />
                    )}
                </div>

                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                        <span className="flex-1 truncate text-[13px] font-medium text-foreground">
                            {topic.title || topic.agent_name || topic.id.slice(0, 12)}
                        </span>
                        <span className="shrink-0 text-[11px] text-muted-foreground/60">
                            {formatListTime(topic.updated_at || topic.created_at)}
                        </span>
                    </div>

                    <div className="mt-0.5 flex items-center gap-1.5">
                        <span className="flex-1 truncate text-[11px] text-muted-foreground">
                            {preview ||
                                (topic.kind === "team"
                                    ? "Team session"
                                    : "Start a conversation")}
                        </span>
                        {topic.kind === "team" && (
                            <span className="shrink-0 rounded-sm bg-foreground/8 px-1 text-[9px] font-medium leading-tight text-muted-foreground">
                                team
                            </span>
                        )}
                        {unread > 0 && (
                            <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-destructive text-[9px] font-medium text-destructive-foreground ring-2 ring-card">
                                {unread > 9 ? "9+" : unread}
                            </span>
                        )}
                    </div>
                </div>
            </button>
        </li>
    );
}

/** Render an avatar for a topic (uses agent_name for DiceBear seed). */
function TopicAvatar({ topic, size = 36 }) {
    // Reuse SessionAvatar by mapping topic → session-like object.
    // SessionAvatar reads kind + name/members for the avatar style.
    return (
        <SessionAvatar
            session={{
                id: topic.session_id || topic.id,
                kind: topic.kind,
                name: topic.agent_name,
                metadata: {},
            }}
            size={size}
        />
    );
}
