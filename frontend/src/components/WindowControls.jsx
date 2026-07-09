import {Minus, Square, X, Copy} from "lucide-react";

import {cn} from "@/lib/utils";

/**
 * WindowControls — macOS-style traffic light buttons (right side on Windows).
 * Only rendered in Electron (window.electron exists).
 *
 * - minimize: minimize window
 * - maximize: toggle maximize/restore (also triggered by double-clicking top bar)
 * - close: close window
 */
export function WindowControls() {
  if (typeof window === "undefined" || !window.electron) return null;

  const electron = window.electron;

  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => electron.window.minimize()}
        className="flex size-7 items-center justify-center rounded-md text-muted-foreground/60 transition hover:bg-muted/30 hover:text-foreground"
        title="Minimize"
      >
        <Minus className="size-3.5"/>
      </button>
      <button
        onClick={() => electron.window.maximizeToggle()}
        className="flex size-7 items-center justify-center rounded-md text-muted-foreground/60 transition hover:bg-muted/30 hover:text-foreground"
        title="Maximize / Restore"
      >
        <Square className="size-3"/>
      </button>
      <button
        onClick={() => electron.window.close()}
        className="flex size-7 items-center justify-center rounded-md text-muted-foreground/60 transition hover:bg-destructive/20 hover:text-destructive"
        title="Close"
      >
        <X className="size-3.5"/>
      </button>
    </div>
  );
}
