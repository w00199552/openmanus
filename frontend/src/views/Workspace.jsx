import {observer} from "mobx-react-lite";
import {useEffect, useState} from "react";
import {Panel, PanelGroup, PanelResizeHandle} from "react-resizable-panels";
import {PanelRightOpen} from "lucide-react";
import {TopNav} from "@/components/TopNav";
import {SessionList} from "@/views/SessionList";
import {ChatPane} from "@/views/ChatPane";
import {Playground} from "@/views/Playground";
import {AgentsView} from "@/views/AgentsView";
import {SkillsView} from "@/views/SkillsView";
import {ToolsView} from "@/views/ToolsView";

// localStorage keys for persisted panel layouts.
const LAYOUT_LEFT = "openmanus.layout.left";
const LAYOUT_MAIN = "openmanus.layout.main";

function loadLayout(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

/**
 * Workspace — top-level app shell with resizable panels.
 *
 * Layout:
 *   ┌──────────────────────────────────────────────────┐
 *   │ TopNav                                            │
 *   ├────────────────────┬─────────────────────────────┤
 *   │ LEFT (50%)         │ RIGHT (50%)                 │
 *   │ ┌──────┬─────────┐ │                             │
 *   │ │List  │ Chat    │ │  Sandbox                    │
 *   │ └──────┴─────────┘ │                             │
 *   └────────────────────┴─────────────────────────────┘
 *
 * Left can collapse to avatar strip width. All separators draggable.
 */
export const Workspace = observer(function Workspace() {
  const [activeView, setActiveView] = useState("chat");
  const [chatCollapsed, setChatCollapsed] = useState(
    () => localStorage.getItem("openmanus.chat.collapsed") === "true",
  );

  const toggleCollapse = () => {
    const next = !chatCollapsed;
    setChatCollapsed(next);
    localStorage.setItem("openmanus.chat.collapsed", String(next));
  };

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-background text-foreground">
      <TopNav activeView={activeView} onNavigate={setActiveView} />

      {activeView === "agents" && (
        <div className="min-h-0 flex-1"><AgentsView /></div>
      )}
      {activeView === "skills" && (
        <div className="min-h-0 flex-1"><SkillsView /></div>
      )}
      {activeView === "tools" && (
        <div className="min-h-0 flex-1"><ToolsView /></div>
      )}

      {activeView === "chat" && (
        <PanelGroup direction="horizontal" className="min-h-0 flex-1">
          {/* ── LEFT: list | chat (or collapsed strip) ───────────────── */}
          <Panel
            key={chatCollapsed ? "left-c" : "left-e"}
            defaultSize={chatCollapsed ? 4 : 50}
            minSize={chatCollapsed ? 4 : 15}
            maxSize={chatCollapsed ? 4 : 70}
          >
            {chatCollapsed ? (
              <div className="relative flex h-full flex-col items-center bg-card">
                <button
                  onClick={toggleCollapse}
                  className="absolute right-0.5 top-0.5 z-10 rounded-md p-1 text-muted-foreground transition hover:bg-sidebar hover:text-foreground"
                  title="Expand"
                >
                  <PanelRightOpen className="size-3.5" />
                </button>
                <SessionList collapsed={true} />
              </div>
            ) : (
              <PanelGroup direction="horizontal" className="h-full">
                <Panel defaultSize={20} minSize={10} maxSize={40}>
                  <SessionList collapsed={false} />
                </Panel>
                <PanelResizeHandle className="sep-bar relative w-1.5 cursor-col-resize">
                  <span className="sep-line pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/60" />
                </PanelResizeHandle>
                <Panel defaultSize={80} minSize={30}>
                  <ChatPane onToggleCollapse={toggleCollapse} />
                </Panel>
              </PanelGroup>
            )}
          </Panel>

          <PanelResizeHandle className="sep-bar relative w-1.5 cursor-col-resize">
            <span className="sep-line pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/60" />
          </PanelResizeHandle>

          {/* ── RIGHT: sandbox ───────────────────────────────────────── */}
          <Panel defaultSize={50} minSize={20}>
            <Playground />
          </Panel>
        </PanelGroup>
      )}
    </div>
  );
});
