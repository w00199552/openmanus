import { Settings, LogIn, Sun, Moon } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/use-theme";
import { WindowControls } from "@/components/window-controls";

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
 * TopNav — global navigation bar (devrajchatribin.com style).
 *
 * Layout: 80px tall, transparent (no backdrop blur), borderless bottom.
 * Logo in ClashDisplay on the left. Nav links centered with the signature
 * double-layer slide + skew hover animation. Active state is pure color
 * contrast (no underline, no dot) — restraint is the point.
 *
 * In Electron: the bar is draggable (appRegion: drag), double-click toggles
 * maximize. Buttons inside opt out with appRegion: no-drag.
 */
export function TopNav({ activeView = "chat", onNavigate }) {
    const handleDoubleClick = () => {
        if (typeof window !== "undefined" && window.electron) {
            window.electron.window.maximizeToggle();
        }
    };

    const { isDark, toggle } = useTheme();

    return (
        <header
            onDoubleClick={handleDoubleClick}
            style={{ appRegion: "drag" }}
            className="relative flex h-14 shrink-0 items-center px-6"
        >
            {/* Logo (left) — ClashDisplay wordmark, pure text */}
            <button
                onClick={() => onNavigate?.("chat")}
                style={{ appRegion: "no-drag" }}
                className="shrink-0 font-display text-xl font-medium tracking-tight text-foreground transition hover:opacity-80"
            >
                OpenManus
            </button>

            {/* Nav items (centered) */}
            <nav
                style={{ appRegion: "no-drag" }}
                className="absolute left-1/2 flex -translate-x-1/2 items-center gap-6"
            >
                {NAV_ITEMS.map((item) => {
                    const isActive = activeView === item.key && item.active;
                    return (
                        <NavLink
                            key={item.key}
                            label={item.label}
                            active={isActive}
                            disabled={!item.active}
                            onClick={() =>
                                item.active && onNavigate?.(item.key)
                            }
                        />
                    );
                })}
            </nav>

            {/* Right: settings + login + window controls */}
            <div
                style={{ appRegion: "no-drag" }}
                className="ml-auto flex items-center gap-2"
            >
                <button
                    onClick={toggle}
                    className="rounded-md p-2 text-muted-foreground transition hover:bg-foreground/5 hover:text-foreground"
                    title={isDark ? "Switch to light" : "Switch to dark"}
                    aria-label="Toggle theme"
                >
                    {/* Sun shows in dark mode (click → light); Moon in light. */}
                    {isDark ? (
                        <Sun className="size-4" />
                    ) : (
                        <Moon className="size-4" />
                    )}
                </button>
                <button
                    className="rounded-md p-2 text-muted-foreground transition hover:bg-foreground/5 hover:text-foreground"
                    title="Settings"
                >
                    <Settings className="size-4" />
                </button>
                <button
                    className="flex items-center gap-1.5 rounded-full border border-border/60 px-3 py-1.5 text-[13px] text-foreground/80 transition hover:border-foreground/30 hover:text-foreground"
                    title="Sign in"
                >
                    <LogIn className="size-3.5" />
                    Sign in
                </button>
                <WindowControls />
            </div>
        </header>
    );
}

/**
 * NavLink — a single nav link with the devraj double-layer slide animation.
 *
 * Two stacked copies of the label live inside an overflow-hidden span:
 *   - Layer A sits in place by default; on hover it slides UP and OUT while
 *     skewing, leaving the slot.
 *   - Layer B waits below (translate-y-[110%] + skew); on hover it slides up
 *     into place and un-skews. The handoff reads as the label rolling over.
 * Both layers run on transform-gpu + 500ms for buttery motion.
 *
 * Active links render in bright foreground; inactive ones in muted gray.
 * Pure color contrast — no underline, no dot (deliberate restraint).
 */
function NavLink({ label, active, disabled, onClick }) {
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            className={cn(
                "group relative",
                disabled && "cursor-default"
            )}
            title={disabled ? `${label} (coming soon)` : label}
        >
            <span
                className={cn(
                    "relative inline-flex items-center overflow-hidden text-sm",
                    active
                        ? "text-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    disabled && "opacity-40"
                )}
            >
                {/* Active indicator: a small lime dot to the LEFT of the label.
                    Slides in alongside the text so the whole row animates as one. */}
                {active && (
                    <span className="mr-1.5 size-1.5 shrink-0 rounded-full bg-accent accent-glow" />
                )}
                <span className="relative inline-flex overflow-hidden">
                    {/* Layer A: in place → slides up & skews out on hover */}
                    <span className="translate-y-0 skew-y-0 transform-gpu transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-[110%] group-hover:skew-y-[12deg]">
                        {label}
                    </span>
                    {/* Layer B: hidden below → slides into place & un-skews on hover.
                        Brighter color so the rollover feels like a refresh. */}
                    <span className="absolute translate-y-[110%] skew-y-[12deg] transform-gpu text-foreground transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-y-0 group-hover:skew-y-0">
                        {label}
                    </span>
                </span>
            </span>
        </button>
    );
}
