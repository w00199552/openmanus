import { Globe, Lock } from "lucide-react";

/**
 * PreviewTool — placeholder for a future web-preview surface.
 *
 * One day this will render sandbox HTML/React output in an iframe. For now
 * it's a styled empty state that signals intent: a fake address bar up top,
 * a centered globe glyph, and a short note. No data, no logic.
 */
export function PreviewTool() {
    return (
        <div className="flex h-full flex-col bg-background">
            {/* fake address bar — hints at what this will become */}
            <div className="flex shrink-0 items-center gap-2 px-4 py-3">
                <div className="flex h-6 flex-1 items-center gap-2 rounded-full border border-border/60 bg-sidebar/30 px-3 text-[11px] text-muted-foreground/60">
                    <Lock className="size-3" />
                    <span className="truncate">preview · coming soon</span>
                </div>
            </div>

            {/* centered empty state */}
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                <span className="flex size-12 items-center justify-center rounded-full bg-foreground/5 ring-1 ring-border/60">
                    <Globe className="size-5 text-foreground/50" />
                </span>
                <div>
                    <p className="font-display text-[15px] font-medium tracking-tight text-foreground">
                        Web Preview
                    </p>
                    <p className="mt-1 max-w-xs text-[12px] leading-relaxed text-muted-foreground">
                        Preview HTML / React output from the sandbox.
                        <br />
                        Coming soon.
                    </p>
                </div>
            </div>
        </div>
    );
}
