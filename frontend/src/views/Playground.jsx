import {useState} from "react";
import {Code2, FolderTree} from "lucide-react";

import {Group, Panel, Separator} from "react-resizable-panels";

import {CodeEditor} from "@/components/playground/CodeEditor";
import {cn} from "@/lib/utils";

// The toolset the playground can tile. Order here = left-to-right order.
const TOOL_DEFS = [
  { key: "sandbox", label: "Sandbox", icon: FolderTree, render: () => <SandboxView /> },
  { key: "ide", label: "Code", icon: Code2, render: () => <CodeEditor /> },
];

const DEFAULT_OPEN = ["sandbox", "ide"];

/**
 * Playground — the right half: a tiled tool surface.
 *
 * Top toolbar: each tool is a toggle — click to open/close it.
 * Bottom: ALL open tools are tiled side-by-side (draggable separators), with
 * Sandbox on the left by convention. This is multi-window tiling (like an
 * editor's split view), not single-tab switching.
 *
 * Vision: which tools are open is decided by the active agent/team (via
 * CopilotKit frontendTool). This scaffold ships Sandbox + Code.
 */
export function Playground() {
  const [open, setOpen] = useState(DEFAULT_OPEN);

  const toggle = (key) => {
    setOpen((cur) =>
      cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key],
    );
  };

  const openDefs = TOOL_DEFS.filter((d) => open.includes(d.key));
  // keep Sandbox first (left-most) by convention
  openDefs.sort((a, b) => {
    if (a.key === "sandbox") return -1;
    if (b.key === "sandbox") return 1;
    return 0;
  });

  return (
    <div className="flex h-full flex-col bg-sidebar">
      {/* ── tool toolbar (toggles) ────────────────────────────────── */}
      <div className="flex items-center gap-1 border-b border-border/60 px-2 py-1.5">
        {TOOL_DEFS.map((def) => {
          const Icon = def.icon;
          const isOpen = open.includes(def.key);
          return (
            <button
              key={def.key}
              onClick={() => toggle(def.key)}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12px] transition",
                isOpen
                  ? "bg-accent/15 text-accent"
                  : "text-muted-foreground/60 hover:text-foreground/70",
              )}
              title={isOpen ? `Close ${def.label}` : `Open ${def.label}`}
            >
              <Icon className="size-3.5" />
              {def.label}
              <span
                className={cn(
                  "ml-0.5 size-1.5 rounded-full",
                  isOpen ? "bg-accent" : "bg-muted-foreground/30",
                )}
              />
            </button>
          );
        })}
      </div>

      {/* ── tiled tool windows ────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden">
        {openDefs.length === 0 ? (
          <EmptyState />
        ) : (
          <TiledGroup defs={openDefs} />
        )}
      </div>
    </div>
  );
}

/**
 * Tile all open tools side-by-side with draggable separators between them.
 * (react-resizable-panels requires Separator as a sibling of Panel inside
 * Group, so we interleave them here.)
 */
function TiledGroup({ defs }) {
  return (
    <Group
      orientation="horizontal"
      className="flex h-full"
      style={{ flexDirection: "row" }}
    >
      {defs.map((def, idx) => (
        <FragmentTile key={def.key} def={def} showSep={idx > 0} />
      ))}
    </Group>
  );
}

function FragmentTile({ def, showSep }) {
  return (
    <>
      {showSep && (
        <Separator className="sep-bar relative w-1.5 cursor-col-resize">
          <span className="sep-line pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/60" />
        </Separator>
      )}
      <Panel id={def.key} minSize="15%">
        <div className="flex h-full flex-col">
          <div className="flex items-center gap-1.5 border-b border-border/60 bg-background/40 px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            <def.icon className="size-3" />
            {def.label}
          </div>
          <div className="flex-1 overflow-hidden">{def.render()}</div>
        </div>
      </Panel>
    </>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full items-center justify-center text-xs text-muted-foreground/60">
      No tool open. Open one from the toolbar above.
    </div>
  );
}

function SandboxView() {
  return (
    <div className="h-full overflow-y-auto bg-sidebar p-3">
      <pre className="font-mono text-[11px] leading-relaxed text-muted-foreground">
{`📁 backend/
   📁 src/openmanus/
   📁 tests/
   📄 pyproject.toml
📁 runtime/
   📄 src/index.js
📁 frontend/
   📁 src/
   📄 package.json`}
      </pre>
    </div>
  );
}
