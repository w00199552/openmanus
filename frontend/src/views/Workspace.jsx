import {observer} from "mobx-react-lite";
import {useEffect, useState} from "react";
import {Group, Panel, Separator} from "react-resizable-panels";
import {TopNav} from "@/components/TopNav";
import {SessionList} from "@/views/SessionList";
import {ChatPane} from "@/views/ChatPane";
import {Playground} from "@/views/Playground";
import {AgentsView} from "@/views/AgentsView";
import {SkillsView} from "@/views/SkillsView";

// localStorage keys for persisted panel layouts (survive session switches).
const LAYOUT_LEFT = "openmanus.layout.left"; // list | chat  (inside left half)
const LAYOUT_MAIN = "openmanus.layout.main"; // leftHalf | rightHalf

// one-time migration from the old "deepopen.*" namespace
["deepopen.layout.left", "deepopen.layout.main"].forEach((oldK) => {
  const newK = oldK.replace("deepopen", "openmanus");
  if (localStorage.getItem(newK) == null) {
    const v = localStorage.getItem(oldK);
    if (v != null) localStorage.setItem(newK, v);
  }
});

function loadLayout(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

/**
 * Workspace — the top-level app shell.
 *
 * Layout:
 *   ┌──────────────────────────────────────────────────┐
 *   │ TopNav                                            │
 *   ├────────────────────┬─────────────────────────────┤
 *   │ LEFT HALF (50%)    │ RIGHT HALF (50%)            │
 *   │ ┌──────┬─────────┐ │ ┌──────────┬──────────────┐ │
 *   │ │Agent/│ Chat     │ │ │ Sandbox  │ Playground   │ │
 *   │ │Team  │ (self-   │ │ │ (files)  │ (IDE/tools)  │ │
 *   │ │list  │ rendered)│ │ │          │              │ │
 *   │ └──────┴─────────┘ │ └──────────┴──────────────┘ │
 *   └────────────────────┴─────────────────────────────┘
 *
 * All separators are draggable. Layouts persist to localStorage so switching
 * sessions (New chat / History) does NOT reset dragged widths.
 */
export const Workspace = observer(function Workspace() {
  const [activeView, setActiveView] = useState("chat");
  const [leftLayout, setLeftLayout] = useState(() =>
    loadLayout(LAYOUT_LEFT, [16, 84]),
  );
  const [mainLayout, setMainLayout] = useState(() =>
    loadLayout(LAYOUT_MAIN, [50, 50]),
  );

  // persist on change (debounced via the lib's own change cadence)
  useEffect(() => {
    localStorage.setItem(LAYOUT_LEFT, JSON.stringify(leftLayout));
  }, [leftLayout]);
  useEffect(() => {
    localStorage.setItem(LAYOUT_MAIN, JSON.stringify(mainLayout));
  }, [mainLayout]);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-background text-foreground">
      <TopNav activeView={activeView} onNavigate={setActiveView} />

      {/* Agents view: full-width, no panels */}
      {activeView === "agents" && (
        <div className="min-h-0 flex-1">
          <AgentsView />
        </div>
      )}

      {/* Skills view: full-width, no panels */}
      {activeView === "skills" && (
        <div className="min-h-0 flex-1">
          <SkillsView />
        </div>
      )}

      {/* Chat view: resizable panels */}
      {activeView === "chat" && (
      <Group
        orientation="horizontal"
        className="flex min-h-0 flex-1"
        style={{ flexDirection: "row" }}
        defaultLayout={mainLayout}
        onLayoutChanged={(l) => setMainLayout(l)}
      >
        {/* ── LEFT HALF: list | chat ─────────────────────────────────── */}
        <Panel id="left" defaultSize="50%" minSize="30%">
          <Group
            orientation="horizontal"
            className="flex h-full"
            style={{ flexDirection: "row" }}
            defaultLayout={leftLayout}
            onLayoutChanged={(l) => setLeftLayout(l)}
          >
            <Panel id="list" minSize="10%" maxSize="45%">
              <SessionList />
            </Panel>
            <Separator className="sep-bar relative w-1.5 cursor-col-resize">
              <span className="sep-line pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/60" />
            </Separator>
            <Panel id="chat" minSize="30%">
              <ChatPane />
            </Panel>
          </Group>
        </Panel>

        <Separator className="sep-bar relative w-1.5 cursor-col-resize">
          <span className="sep-line pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/60" />
        </Separator>

        {/* ── RIGHT HALF: sandbox | playground ───────────────────────── */}
        <Panel id="right" defaultSize="50%" minSize="30%">
          <Playground />
        </Panel>
      </Group>
      )}
    </div>
  );
});
