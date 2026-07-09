import {LogIn, Settings, Sparkles} from "lucide-react";

import {cn} from "@/lib/utils";

// Nav items with "active" = implemented (clickable).
const NAV_ITEMS = [
  { key: "chat", label: "Chat", active: true },
  { key: "agents", label: "Agents", active: true },
  { key: "skills", label: "Skills", active: true },
  { key: "tools", label: "Tools", active: true },
  { key: "wiki", label: "Wiki" },
  { key: "dashboard", label: "Dashboard" },
  { key: "docs", label: "Docs" },
];

/**
 * TopNav — global navigation bar. The active view is controlled by the parent
 * (App or Workspace) via `activeView` + `onNavigate`.
 *
 * @param {{ activeView: string, onNavigate: (key: string) => void }} props
 */
export function TopNav({ activeView = "chat", onNavigate }) {
  return (
    <header className="relative flex h-11 shrink-0 items-center border-b border-border/60 px-3">
      {/* Logo (left) */}
      <button
        onClick={() => onNavigate?.("chat")}
        className="flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-sm font-semibold"
      >
        <Sparkles className="size-3.5 text-accent" />
        OpenManus
      </button>

      {/* Nav items (centered) */}
      <nav className="absolute left-1/2 flex -translate-x-1/2 items-center gap-0.5">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            onClick={() => item.active && onNavigate?.(item.key)}
            disabled={!item.active}
            className={cn(
              "relative rounded-md px-2.5 py-1 text-[13px] transition",
              activeView === item.key && item.active
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground/70",
              !item.active && "cursor-default opacity-50",
            )}
            title={item.active ? item.label : `${item.label} (coming soon)`}
          >
            {item.label}
            {activeView === item.key && item.active && (
              <span className="absolute -bottom-[9px] left-2 right-2 h-0.5 rounded-full bg-accent" />
            )}
          </button>
        ))}
      </nav>

      {/* Right: settings + login */}
      <div className="ml-auto flex items-center gap-1">
        <button
          className="rounded-md p-1.5 text-muted-foreground transition hover:bg-card hover:text-foreground"
          title="Settings"
        >
          <Settings className="size-4" />
        </button>
        <button
          className="flex items-center gap-1.5 rounded-md border border-border/60 px-2.5 py-1 text-[13px] text-foreground/80 transition hover:border-accent/40"
          title="Sign in"
        >
          <LogIn className="size-3.5" />
          Sign in
        </button>
      </div>
    </header>
  );
}
