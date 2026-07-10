import {observer} from "mobx-react-lite";
import {useState} from "react";
import {Group, Panel, Separator} from "react-resizable-panels";
import {PanelRightOpen} from "lucide-react";
import {TopNav} from "@/components/TopNav";
import {SessionList} from "@/views/SessionList";
import {ChatPane} from "@/views/ChatPane";
import {Playground} from "@/views/Playground";
import {AgentsView} from "@/views/AgentsView";
import {SkillsView} from "@/views/SkillsView";
import {ToolsView} from "@/views/ToolsView";

/**
 * Workspace — top-level app shell.
 *
 * Panel size format (react-resizable-panels v4):
 *   number  = pixels (e.g. 200 = 200px)
 *   string  = percentage (e.g. "50" = 50%, "20%" = 20%)
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
        <Group
          key={chatCollapsed ? "main-c" : "main-e"}
          orientation="horizontal"
          className="min-h-0 flex-1"
          defaultLayout={
            chatCollapsed
              ? {left: 4, right: 96}
              : {left: 50, right: 50}
          }
        >
          {/* ── LEFT: list | chat (or collapsed strip) ───────────────── */}
          <Panel
            id="left"
            defaultSize={chatCollapsed ? 4 : 50}
            minSize={chatCollapsed ? 4 : 15}
            maxSize={chatCollapsed ? 4 : 80}
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
              <Group
                orientation="horizontal"
                className="h-full"
                defaultLayout={{list: 20, chat: 80}}
              >
                <Panel id="list" defaultSize={20} minSize={10} maxSize={40}>
                  <SessionList collapsed={false} />
                </Panel>
                <Separator className="sep-bar relative w-1.5 cursor-col-resize">
                  <span className="sep-line pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/60" />
                </Separator>
                <Panel id="chat" defaultSize={80} minSize={30}>
                  <ChatPane onToggleCollapse={toggleCollapse} />
                </Panel>
              </Group>
            )}
          </Panel>

          <Separator className="sep-bar relative w-1.5 cursor-col-resize">
            <span className="sep-line pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/60" />
          </Separator>

          {/* ── RIGHT: sandbox ───────────────────────────────────────── */}
          <Panel id="right" defaultSize={50} minSize={20}>
            <Playground />
          </Panel>
        </Group>
      )}
    </div>
  );
});
