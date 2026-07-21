import { observer } from "mobx-react-lite";
import { useEffect, useState } from "react";
import { Search, Trash2 } from "lucide-react";

import { useStore } from "@/hooks/use-store";
import { SessionAvatar } from "@/components/avatar";
import { formatListTime } from "@/utils/time";
import { cn } from "@/lib/utils";

/**
 * SessionList — left rail, WeChat/Feishu style.
 *
 * Each row is a 2-line card:
 *   ┌─────────────────────────────────────┐
 *   │ [avatar]  title            12:30 ●  │  ← title + time + status
 *   │           preview text…     ⟳       │  ← last message preview + running
 *   └─────────────────────────────────────┘
 *
 * Avatars: single face for root/subagent (DiceBear, stable per id/role),
 * overlapping faces for a team. A top search box filters by title + preview.
 * Running sessions show a spinner; unread shows a red badge.
 */
export const SessionList = observer(function SessionList({
    collapsed = false,
}) {
    const { sessions } = useStore();
    const [query, setQuery] = useState("");

    useEffect(() => {
        sessions.load();
    }, [sessions]);

    // Collapsed mode: narrow strip showing only avatars
    if (collapsed) {
        const all = [...sessions.rootSessions, ...sessions.taskSessions];
        return (
            <div className="flex h-full flex-col items-center gap-1 overflow-y-auto bg-card py-3">
                {all.map((s) => (
                    <button
                        key={s.id}
                        onClick={() => sessions.select(s.id)}
                        className="relative shrink-0 rounded-lg p-1 transition hover:bg-sidebar/40"
                        title={s.title || s.id.slice(0, 12)}
                    >
                        <SessionAvatar session={s} size={32} />
                        {s.id === sessions.activeId && (
                            <span className="absolute -left-0.5 top-1/2 h-6 w-1 -translate-y-1/2 rounded-full bg-accent" />
                        )}
                        {sessions.unreadCount(s.id) > 0 && (
                            <span className="absolute -right-0.5 -top-0.5 size-3.5 rounded-full bg-destructive text-[8px] font-bold text-white flex items-center justify-center">
                                {sessions.unreadCount(s.id)}
                            </span>
                        )}
                    </button>
                ))}
            </div>
        );
    }

    // filter both groups by the search query (title + preview)
    const match = (s) => {
        if (!query.trim()) return true;
        const q = query.trim().toLowerCase();
        return (
            (s.title || "").toLowerCase().includes(q) ||
            (s.metadata?.preview || "").toLowerCase().includes(q)
        );
    };
    const roots = sessions.rootSessions.filter(match);
    const tasks = sessions.taskSessions.filter(match);

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
                {sessions.loading && (
                    <p className="px-2.5 py-3 text-xs text-muted-foreground">
                        Loading…
                    </p>
                )}
                {sessions.error && (
                    <p className="px-2.5 py-2 text-xs text-destructive">
                        {sessions.error}
                    </p>
                )}

                {!sessions.loading && (
                    <>
                        {/* DEFAULT group — the entry agent(s) */}
                        <Section
                            title="Default"
                            empty={roots.length === 0}
                            emptyHint={query.trim() ? "No matches." : undefined}
                        >
                            <ul className="space-y-1">
                                {roots.map((s) => (
                                    <SessionItem
                                        key={s.id}
                                        session={s}
                                        unread={sessions.unreadCount(s.id)}
                                        active={s.id === sessions.activeId}
                                        onSelect={() => sessions.select(s.id)}
                                        onDelete={() => sessions.remove(s.id)}
                                    />
                                ))}
                            </ul>
                        </Section>

                        {/* TASKS & TEAMS group — derived team/subagent work */}
                        <Section
                            title="Tasks & Teams"
                            empty={tasks.length === 0}
                            emptyHint={
                                query.trim() ? "No matches." : "No tasks yet."
                            }
                        >
                            <ul className="space-y-1">
                                {tasks.map((s) => (
                                    <SessionItem
                                        key={s.id}
                                        session={s}
                                        unread={sessions.unreadCount(s.id)}
                                        active={s.id === sessions.activeId}
                                        onSelect={() => sessions.select(s.id)}
                                        onDelete={() => sessions.remove(s.id)}
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

/** A titled group section; renders nothing visually when there's no content. */
function Section({ title, children, empty, emptyHint }) {
    if (empty && !emptyHint) return null; // hide empty groups with no hint
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

function SessionItem({ session, unread, active, onSelect, onDelete }) {
    const isTeam = session.kind === "team";
    const isRunning = session.status === "running";
    const preview = session.metadata?.preview || "";

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

                {/* avatar with a live "pulse" dot when the agent is working */}
                <div className="relative mt-0.5">
                    <SessionAvatar session={session} size={36} />
                    {isRunning && (
                        <span className="absolute -bottom-0.5 -right-0.5 size-3 rounded-full bg-accent ring-2 ring-card animate-pulse-dot" />
                    )}
                </div>

                {/* two-line content */}
                <div className="min-w-0 flex-1">
                    {/* line 1: title + time (the running state shows as a pulse on the avatar) */}
                    <div className="flex items-center gap-1.5">
                        <span className="flex-1 truncate text-[13px] font-medium text-foreground">
                            {session.title || session.id.slice(0, 12)}
                        </span>
                        <span className="shrink-0 text-[10px] text-muted-foreground/60">
                            {formatListTime(
                                session.updated_at || session.created_at
                            )}
                        </span>
                    </div>

                    {/* line 2: preview + badges */}
                    <div className="mt-0.5 flex items-center gap-1.5">
                        <span className="flex-1 truncate text-[11px] text-muted-foreground">
                            {preview ||
                                (isTeam
                                    ? "Team session"
                                    : "Start a conversation")}
                        </span>
                        {isTeam && (
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

                <Trash2
                    className="size-3 shrink-0 self-center opacity-0 transition group-hover:opacity-60 hover:!opacity-100 hover:text-destructive"
                    onClick={(e) => {
                        e.stopPropagation();
                        onDelete();
                    }}
                />
            </button>
        </li>
    );
}
