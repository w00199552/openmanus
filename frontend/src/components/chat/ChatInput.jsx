import {useEffect, useRef, useState} from "react";
import {AtSign, Cpu, Paperclip, Plus, Send, Square} from "lucide-react";

import {cn} from "@/lib/utils";
import {Tooltip, TooltipContent, TooltipTrigger,} from "@/components/ui/tooltip";

/**
 * ChatInput — ZCode-style input bar.
 *
 * Layout: a single row of toolbar buttons on the LEFT, a multi-line textarea
 * filling the middle that auto-grows (up to a max height), and the send/stop
 * button on the RIGHT. The toolbar holds:
 *   +  new conversation  (starts a fresh default thread; bounds context)
 *   📎 attach            (placeholder)
 *   ⚙️ model picker       (placeholder)
 *   @  mention / team     (placeholder)
 *
 * Enter sends; Shift+Enter inserts a newline. The textarea auto-resizes via a
 * measured ref (no scrollbars until the max height).
 */
export function ChatInput({ onSend, onStop, onNewChat, isLoading, showNewChat = false }) {
  const [value, setValue] = useState("");
  const taRef = useRef(null);

  // auto-grow: reset height then fit to scrollHeight, capped by max-h CSS.
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text || isLoading) return;
    onSend(text);
    setValue("");
  };

  return (
    <div className="px-2 pb-3 pt-2">
      <div className="content-narrow">
        <div className="rounded-xl border border-border/60 bg-card px-2.5 py-2 transition focus-within:border-accent/40">
          {/* textarea */}
          <textarea
            ref={taRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder="Message manus…  (Shift+Enter for newline)"
            className="block max-h-52 min-h-[2.75rem] w-full resize-none bg-transparent px-1 text-[14px] leading-relaxed outline-none placeholder:text-muted-foreground/50"
          />

          {/* toolbar row: tools on the left, send on the right */}
          <div className="mt-1.5 flex items-center gap-1">
            {/* new conversation — only on the default entry (resets its history) */}
            {showNewChat && (
              <ToolBtn label="New conversation" onClick={onNewChat}>
                <Plus className="size-4" />
              </ToolBtn>
            )}
            {/* attach (placeholder) */}
            <ToolBtn label="Attach (coming soon)">
              <Paperclip className="size-4" />
            </ToolBtn>
            {/* model picker (placeholder) */}
            <ToolBtn label="Model (coming soon)">
              <Cpu className="size-4" />
            </ToolBtn>
            {/* mention / team (placeholder) */}
            <ToolBtn label="Mention / delegate (coming soon)">
              <AtSign className="size-4" />
            </ToolBtn>

            <div className="flex-1" />

            {/* send / stop */}
            {isLoading ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={onStop}
                    className="flex size-7 items-center justify-center rounded-md bg-destructive/15 text-destructive transition hover:bg-destructive/25"
                  >
                    <Square className="size-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top">Stop</TooltipContent>
              </Tooltip>
            ) : (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    onClick={submit}
                    disabled={!value.trim()}
                    className={cn(
                      "flex size-7 items-center justify-center rounded-md transition",
                      value.trim()
                        ? "bg-accent/15 text-accent hover:bg-accent/25"
                        : "bg-muted/30 text-muted-foreground/40",
                    )}
                  >
                    <Send className="size-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top">Send</TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * A small square toolbar button (icon-only, ghost style) with a Radix tooltip
 * label shown on hover. The provider lives in ChatPane.
 */
function ToolBtn({ children, label, onClick }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          className="rounded-md p-1.5 text-muted-foreground transition hover:bg-sidebar/60 hover:text-foreground"
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}
