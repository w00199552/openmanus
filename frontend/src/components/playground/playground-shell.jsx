import { useRef, useState } from "react";
import { FolderTree, Globe, TerminalSquare } from "lucide-react";

import { cn } from "@/lib/utils";
import { SandboxTool } from "@/views/playground";
import { PreviewTool } from "@/components/playground/preview-tool";
import { TerminalTool } from "@/components/playground/terminal-tool";
import {
    PlaygroundContext,
} from "@/components/playground/playground-context";

/**
 * PlaygroundShell — the right-rail container that hosts multiple "tools".
 *
 * Each tool registers { id, label, icon, Component }:
 *   - Component: rendered in the content area (takes the full remaining height)
 *
 * The toolbar's LEFT side is a pill-style switcher (restrained, no accent —
 * tool selection is categorization, not state). The toolbar's RIGHT side is
 * an empty slot whose DOM ref is published via PlaygroundContext; the active
 * tool can `createPortal` its own contextual actions (file name + Save, etc.)
 * into that slot — keeping tool state local while the toolbar stays unified.
 *
 * Tools mount-once and are hidden via `hidden` when inactive, so their
 * internal state (expanded dirs, open file, scroll position) survives a
 * round-trip between tools.
 *
 * Adding a 4th tool later = push one object into TOOLS. No shell changes.
 */

const TOOLS = [
    {
        id: "sandbox",
        label: "Sandbox",
        icon: FolderTree,
        Component: SandboxTool,
    },
    {
        id: "preview",
        label: "Preview",
        icon: Globe,
        Component: PreviewTool,
    },
    {
        id: "terminal",
        label: "Terminal",
        icon: TerminalSquare,
        Component: TerminalTool,
    },
];

export function PlaygroundShell() {
    const [activeId, setActiveId] = useState("sandbox");
    // DOM ref to the toolbar's right slot — published via context so the
    // active tool can portal its actions into it.
    const toolbarRightRef = useRef(null);

    return (
        <PlaygroundContext.Provider value={toolbarRightRef}>
            <div className="flex h-full flex-col">
                {/* toolbar — single 44px row, matches the chat-pane header */}
                <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border/60 px-3">
                    {/* LEFT: tool switcher (pill-style, restrained — no accent) */}
                    <div className="flex items-center gap-1">
                        {TOOLS.map((tool) => {
                            const Icon = tool.icon;
                            const isActive = tool.id === activeId;
                            return (
                                <button
                                    key={tool.id}
                                    onClick={() => setActiveId(tool.id)}
                                    className={cn(
                                        "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors duration-200",
                                        isActive
                                            ? "bg-foreground/8 text-foreground"
                                            : "text-muted-foreground hover:text-foreground/80"
                                    )}
                                >
                                    <Icon className="size-3.5" />
                                    {tool.label}
                                </button>
                            );
                        })}
                    </div>

                    <div className="flex-1" />

                    {/* RIGHT: slot for the active tool's contextual actions.
                        Tools portal their actions here via PlaygroundContext. */}
                    <div ref={toolbarRightRef} className="flex items-center gap-2" />
                </div>

                {/* content area — tools mount-once and hide when inactive so
                    their internal state (sandbox tree, open file, etc.) survives */}
                <div className="min-h-0 flex-1">
                    {TOOLS.map((tool) => {
                        const ToolComponent = tool.Component;
                        return (
                            <div
                                key={tool.id}
                                className={cn(
                                    "h-full",
                                    tool.id === activeId ? "block" : "hidden"
                                )}
                            >
                                <ToolComponent />
                            </div>
                        );
                    })}
                </div>
            </div>
        </PlaygroundContext.Provider>
    );
}
