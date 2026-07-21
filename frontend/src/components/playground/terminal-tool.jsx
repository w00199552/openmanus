import { TerminalSquare } from "lucide-react";

/**
 * TerminalTool — placeholder for a future shell surface.
 *
 * One day this will pipe a PTY from the backend. For now it's a styled empty
 * state dressed like a terminal: deep-black canvas, monospace type, a fake
 * prompt line with a blinking lime cursor (reusing .typing-cursor). No data.
 */
export function TerminalTool() {
    return (
        <div className="flex h-full flex-col bg-background font-mono">
            {/* fake prompt line — the blinking cursor sells the "live terminal" feel */}
            <div className="shrink-0 px-4 py-3 text-[12px] leading-relaxed">
                <span className="text-muted-foreground/60">$ </span>
                <span className="text-foreground/80">openmanus</span>
                <span className="typing-cursor" />
            </div>

            {/* centered empty state */}
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 text-center font-sans">
                <span className="flex size-12 items-center justify-center rounded-full bg-foreground/5 ring-1 ring-border/60">
                    <TerminalSquare className="size-5 text-foreground/50" />
                </span>
                <div>
                    <p className="font-display text-[15px] font-medium tracking-tight text-foreground">
                        Terminal
                    </p>
                    <p className="mt-1 max-w-xs text-[12px] leading-relaxed text-muted-foreground">
                        Run shell commands and inspect the agent's runtime output.
                        <br />
                        Coming soon.
                    </p>
                </div>
            </div>
        </div>
    );
}
