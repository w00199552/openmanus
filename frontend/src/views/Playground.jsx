import {useState, useEffect, useCallback, useRef} from "react";
import {createPortal} from "react-dom";
import {observer} from "mobx-react-lite";
import {
  ChevronRight, ChevronDown, FileText, FileCode, File, Folder, FolderOpen,
  Save, RefreshCw, Loader2, FolderTree, FilePlus, FolderPlus, Trash2,
} from "lucide-react";
import MDEditor from "@uiw/react-md-editor";
import {Highlight, themes} from "prism-react-renderer";
import {Group, Panel, Separator} from "react-resizable-panels";

import {useStore} from "@/hooks/useStore";
import {cn} from "@/lib/utils";
import {ConfirmDialog} from "@/components/sandbox/ConfirmDialog";

/**
 * Playground — file tree + content editor for the Sandbox.
 *
 * All data operations are delegated to SandboxStore (workdir, cd, file CRUD).
 * This component is a thin render layer: it calls store methods and manages
 * only UI state (expanded dirs, open file, draft, dirty).
 *
 * Tree: depth=1 on load (collapsed dirs); children are lazy-loaded on expand.
 * Right: file content (markdown editor / code viewer / text).
 * Live refresh: watchdog SSE via sandbox.watchUrl.
 */
export const Playground = observer(function Playground() {
  const {sandbox} = useStore();
  const [tree, setTree] = useState(null);
  const [expanded, setExpanded] = useState(new Set());
  // childrenByDir[path] = FileNode[] (lazy-loaded)
  const [childrenByDir, setChildrenByDir] = useState({});
  // loadingByDir[path] = true while fetching children
  const [loadingByDir, setLoadingByDir] = useState(new Set());
  const [file, setFile] = useState(null);
  const [draft, setDraft] = useState("");
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Context menu + modal state
  // modal: {mode: 'delete'|'newFile'|'newDir', node} | null
  const [modal, setModal] = useState(null);

  // Refs for SSE callback (avoids re-subscribing watchdog when file/dirty change)
  const fileRef = useRef(file);
  const dirtyRef = useRef(dirty);
  const expandedRef = useRef(expanded);
  fileRef.current = file;
  dirtyRef.current = dirty;
  expandedRef.current = expanded;

  const loadTree = useCallback(async () => {
    try {
      const data = await sandbox.loadTree();
      setTree(data);
      setExpanded(new Set());
      setChildrenByDir({});
      setLoadingByDir(new Set());
    } catch { /* ignore */ }
    setLoading(false);
  }, [sandbox]);

  const loadChildren = useCallback(async (dirPath) => {
    if (childrenByDir[dirPath]) return;
    setLoadingByDir((prev) => new Set(prev).add(dirPath));
    try {
      const children = await sandbox.loadChildren(dirPath);
      setChildrenByDir((prev) => ({...prev, [dirPath]: children}));
    } catch { /* ignore */ }
    finally {
      setLoadingByDir((prev) => {
        const next = new Set(prev);
        next.delete(dirPath);
        return next;
      });
    }
  }, [childrenByDir, sandbox]);

  /**
   * Refresh a single directory's children (bypasses cache).
   * Used by watchdog events to update only the affected parent dir,
   * instead of reloading the entire tree.
   */
  const refreshDir = useCallback(async (dirPath) => {
    try {
      const children = await sandbox.loadChildren(dirPath);
      setChildrenByDir((prev) => ({...prev, [dirPath]: children}));
    } catch { /* ignore */ }
  }, [sandbox]);

  /**
   * Refresh the root-level children (first level of workdir).
   * Used when a file/dir is created/deleted at the top level.
   */
  const refreshRoot = useCallback(async () => {
    try {
      const data = await sandbox.loadTree();
      setTree(data);
      // preserve expanded dirs + loaded children — only swap root children
    } catch { /* ignore */ }
  }, [sandbox]);

  const loadFile = useCallback(async (path) => {
    try {
      const data = await sandbox.loadFile(path);
      setFile(data);
      setDraft(data.content);
      setDirty(false);
    } catch { /* ignore */ }
  }, [sandbox]);

  const saveFile = useCallback(async () => {
    if (!file || !dirty) return;
    setSaving(true);
    try {
      await sandbox.saveFile(file.path, draft);
      setDirty(false);
    } catch { /* ignore */ }
    setSaving(false);
  }, [file, draft, dirty, sandbox]);

  // initial load
  useEffect(() => {
    loadTree();
  }, [loadTree]);

  // reload tree when workdir changes (cd or session switch)
  useEffect(() => {
    if (sandbox.workdir) {
      loadTree();
      setFile(null);
    }
  }, [sandbox.workdir, loadTree]);

  // watchdog: live refresh — targeted, preserves expand state.
  // For created/deleted/moved: refresh only the parent dir's children.
  // For modified: reload the open file if it matches.
  const wdPending = useRef(new Set()); // parent dirs pending refresh
  const wdTimer = useRef(null);
  useEffect(() => {
    const flush = () => {
      const dirs = wdPending.current;
      wdPending.current = new Set();
      // refresh root if "" is pending, else refresh specific expanded dirs
      for (const dir of dirs) {
        if (dir === "") {
          refreshRoot();
        } else if (expandedRef.current.has(dir)) {
          refreshDir(dir);
        }
      }
    };
    const es = new EventSource(sandbox.watchUrl);
    es.onmessage = (ev) => {
      try {
        const evt = JSON.parse(ev.data);
        if (evt.type === "ping") return;
        if (evt.type === "created" || evt.type === "deleted" || evt.type === "moved") {
          // parent dir of the changed file
          const slash = evt.path.lastIndexOf("/");
          const parent = slash >= 0 ? evt.path.substring(0, slash) : "";
          wdPending.current.add(parent);
          // also refresh the dir itself if a directory was created/deleted
          if (evt.type === "created" || evt.type === "deleted") {
            wdPending.current.add(evt.path);
          }
          clearTimeout(wdTimer.current);
          wdTimer.current = setTimeout(flush, 200);
        }
        if (evt.type === "modified") {
          const f = fileRef.current;
          if (f && evt.path === f.path && !dirtyRef.current) {
            loadFile(f.path);
          }
        }
      } catch { /* ignore */ }
    };
    return () => { es.close(); clearTimeout(wdTimer.current); };
  }, [sandbox.workdir, sandbox, loadFile, refreshDir, refreshRoot]);

  const toggleDir = (path) => {
    const wasOpen = expanded.has(path);
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    // lazy load on first expand
    if (!wasOpen && !childrenByDir[path]) loadChildren(path);
  };

  const onSelectFile = (path) => {
    if (dirty && !confirm("Discard unsaved changes?")) return;
    loadFile(path);
  };

  // ── Context menu actions ────────────────────────────────────────────────

  const handleDelete = async (node) => {
    try {
      await sandbox.deletePath(node.path);
      // if we deleted the currently open file, clear it
      if (file && file.path === node.path) setFile(null);
      // watchdog will auto-refresh the tree
    } catch { /* error shown by dialog */ }
    setModal(null);
  };

  const handleNewFile = async (node, name) => {
    const parentPath = node.type === "dir" ? node.path : "";
    const fullPath = parentPath ? `${parentPath}/${name}` : name;
    try {
      await sandbox.createFile(fullPath);
      // watchdog will auto-refresh the tree
    } catch { /* error shown by dialog */ }
    setModal(null);
  };

  const handleNewDir = async (node, name) => {
    const parentPath = node.type === "dir" ? node.path : "";
    const fullPath = parentPath ? `${parentPath}/${name}` : name;
    try {
      await sandbox.createDir(fullPath);
      // watchdog will auto-refresh the tree
    } catch { /* error shown by dialog */ }
    setModal(null);
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="size-4 animate-spin text-muted-foreground"/>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* toolbar */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border/60 px-3 py-2">
        <span className="text-[12px] font-medium text-muted-foreground">Sandbox</span>
        <button onClick={loadTree} className="rounded-md p-1 text-muted-foreground transition hover:bg-card hover:text-foreground" title="Refresh">
          <RefreshCw className="size-3.5"/>
        </button>
        <div className="flex-1"/>
        {file && (
          <>
            <span className="text-[11px] text-muted-foreground/60">{file.name}{dirty ? " •" : ""}</span>
            <button
              onClick={saveFile}
              disabled={!dirty || saving}
              className={cn(
                "flex items-center gap-1 rounded-md px-2 py-1 text-[12px] transition",
                dirty ? "bg-accent/15 text-accent hover:bg-accent/25" : "text-muted-foreground/40 cursor-default",
              )}
            >
              {saving ? <Loader2 className="size-3 animate-spin"/> : <Save className="size-3"/>}
              Save
            </button>
          </>
        )}
      </div>

      {/* tree + content (resizable) */}
      <Group orientation="horizontal" className="min-h-0 flex-1">
        {/* file tree */}
        <Panel id="sandbox-tree" defaultSize="25%" minSize="12%" maxSize="50%">
          <div className="flex h-full flex-col bg-sidebar/20">
            {/* current workdir header */}
            {sandbox.workdir && (
              <div className="flex shrink-0 items-center gap-1.5 border-b border-border/40 px-3 py-1.5" title={sandbox.workdir}>
                <FolderTree className="size-3.5 shrink-0 text-sky-400/70"/>
                <span className="truncate text-[11px] font-medium text-foreground/80">{sandbox.workdir}</span>
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
              {tree && (
                <TreeContainer
                  node={tree}
                  expanded={expanded}
                  toggleDir={toggleDir}
                  onSelect={onSelectFile}
                  selectedPath={file?.path}
                  childrenByDir={childrenByDir}
                  loadingByDir={loadingByDir}
                  onContext={setModal}
                />
              )}
            </div>
          </div>
        </Panel>

        <Separator className="sep-bar relative w-1.5 cursor-col-resize">
          <span className="sep-line pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/60" />
        </Separator>

        {/* content */}
        <Panel id="sandbox-content" minSize="30%">
          <div className="h-full overflow-auto" data-color-mode="dark">
            {file ? (
              <FileEditor file={file} draft={draft} setDraft={(v) => { setDraft(v); setDirty(true); }}/>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Select a file
              </div>
            )}
          </div>
        </Panel>
      </Group>

      {/* Context menu modal (delete confirm / new file/dir input) */}
      {modal && (
        <ConfirmDialog
          open
          mode={modal.mode}
          title={
            modal.mode === "delete" ? `Delete "${modal.node.name}"?`
            : modal.mode === "newFile" ? "New File"
            : "New Folder"
          }
          message={
            modal.mode === "delete"
              ? modal.node.type === "dir"
                ? `This will recursively delete the folder and all its contents.`
                : `This action cannot be undone.`
              : undefined
          }
          onCancel={() => setModal(null)}
          onConfirm={
            modal.mode === "delete" ? () => handleDelete(modal.node)
            : modal.mode === "newFile" ? (name) => handleNewFile(modal.node, name)
            : (name) => handleNewDir(modal.node, name)
          }
        />
      )}
    </div>
  );
});

// ─── Tree container (native onContextMenu + positioned menu) ─────────────────

/**
 * TreeContainer uses a NATIVE onContextMenu on the wrapper div to capture
 * which node was right-clicked, then renders a lightweight positioned menu.
 * This avoids Radix ContextMenuTrigger's per-child event listener binding
 * which caused UI freezes when the tree re-renders (dozens of nodes).
 */
function TreeContainer({node, expanded, toggleDir, onSelect, selectedPath, childrenByDir, loadingByDir, onContext}) {
  const [menu, setMenu] = useState(null); // {x, y, node} | null

  const childProps = {expanded, toggleDir, onSelect, selectedPath, childrenByDir, loadingByDir};

  const handleContextMenu = (e) => {
    e.preventDefault();
    const wrapper = e.target.closest("[data-path]");
    const targetNode = wrapper
      ? {
          path: wrapper.getAttribute("data-path"),
          type: wrapper.getAttribute("data-type"),
          name: wrapper.getAttribute("data-name"),
        }
      : null;
    setMenu({x: e.clientX, y: e.clientY, node: targetNode});
  };

  // close on any click outside, ESC, or scroll
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener("click", close);
    window.addEventListener("contextmenu", close, true);
    const esc = (e) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("contextmenu", close, true);
      window.removeEventListener("keydown", esc);
    };
  }, [menu]);

  const isDir = menu?.node?.type === "dir";

  return (
    <>
      <div className="min-h-full" onContextMenu={handleContextMenu}>
        {(node.children || []).map((child) => (
          <TreeNode key={child.path || child.name} node={child} {...childProps} depth={1}/>
        ))}
      </div>
      {menu && createPortal(
        <div
          className="fixed z-[100] min-w-[160px] overflow-hidden rounded-md border border-border/80 bg-popover p-1 py-1.5 text-popover-foreground shadow-xl anim-rise"
          style={{left: menu.x, top: menu.y}}
          onClick={(e) => e.stopPropagation()}
        >
          {isDir && (
            <>
              <MenuItem icon={FilePlus} label="New File" onClick={() => { onContext({mode: "newFile", node: menu.node}); setMenu(null); }}/>
              <MenuItem icon={FolderPlus} label="New Folder" onClick={() => { onContext({mode: "newDir", node: menu.node}); setMenu(null); }}/>
              <MenuDivider/>
            </>
          )}
          {!menu.node && (
            <>
              <MenuItem icon={FilePlus} label="New File" onClick={() => { onContext({mode: "newFile", node: {type: "dir", path: "", name: ""}}); setMenu(null); }}/>
              <MenuItem icon={FolderPlus} label="New Folder" onClick={() => { onContext({mode: "newDir", node: {type: "dir", path: "", name: ""}}); setMenu(null); }}/>
              <MenuDivider/>
            </>
          )}
          {menu.node && (
            <MenuItem icon={Trash2} label="Delete" danger onClick={() => { onContext({mode: "delete", node: menu.node}); setMenu(null); }}/>
          )}
        </div>,
        document.body,
      )}
    </>
  );
}

function MenuItem({icon: Icon, label, onClick, danger}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full cursor-pointer items-center gap-2 rounded-sm px-2.5 py-1.5 text-[13px] outline-none transition",
        danger
          ? "text-destructive hover:bg-destructive/10"
          : "text-popover-foreground hover:bg-accent/15 hover:text-accent",
      )}
    >
      <Icon className="size-3.5"/>
      {label}
    </button>
  );
}

function MenuDivider() {
  return <div className="my-1 h-px bg-border/60"/>;
}

// ─── Tree node (recursive, lazy) ─────────────────────────────────────────────

function TreeNode({node, expanded, toggleDir, onSelect, selectedPath, depth, childrenByDir, loadingByDir}) {
  const isDir = node.type === "dir";
  const isOpen = expanded.has(node.path);
  const isLoading = loadingByDir.has(node.path);
  const children = isDir ? (childrenByDir[node.path] || null) : null;

  const childProps = {expanded, toggleDir, onSelect, selectedPath, childrenByDir, loadingByDir};

  return (
    <div data-path={node.path} data-type={node.type} data-name={node.name}>
      <button
        onClick={() => isDir ? toggleDir(node.path) : onSelect(node.path)}
        className={cn(
          "flex w-full items-center gap-1 rounded-md px-2 py-1 text-[13px] transition",
          !isDir && selectedPath === node.path
            ? "bg-accent/10 text-accent"
            : "text-muted-foreground/90 hover:bg-sidebar/40 hover:text-foreground",
        )}
        style={{paddingLeft: `${depth * 12 + 4}px`}}
      >
        {isDir ? (
          <>
            {isLoading ? (
              <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground/50"/>
            ) : (
              isOpen ? <ChevronDown className="size-3.5 shrink-0"/> : <ChevronRight className="size-3.5 shrink-0"/>
            )}
            {isOpen ? <FolderOpen className="size-3.5 shrink-0 text-sky-400/70"/> : <Folder className="size-3.5 shrink-0 text-sky-400/70"/>}
          </>
        ) : (
          <>
            <span className="w-3 shrink-0"/>
            <FileIcon name={node.name}/>
          </>
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isDir && isOpen && (
        isLoading
          ? null
          : (children || []).map((child) => (
            <TreeNode key={child.path || child.name} node={child} {...childProps} depth={depth + 1}/>
          ))
      )}
    </div>
  );
}

function FileIcon({name}) {
  const ext = name.split(".").pop()?.toLowerCase();
  if (ext === "md") return <FileText className="size-3.5 shrink-0 text-accent/60"/>;
  if (["py", "js", "jsx", "ts", "tsx", "sh", "json", "yaml", "yml", "css"].includes(ext)) return <FileCode className="size-3.5 shrink-0 text-muted-foreground/50"/>;
  return <File className="size-3.5 shrink-0 text-muted-foreground/40"/>;
}

// ─── File editor ────────────────────────────────────────────────────────────

function FileEditor({file, draft, setDraft}) {
  if (file.file_type === "markdown") {
    return (
      <div className="h-full" data-color-mode="dark">
        <MDEditor value={draft} onChange={(v) => setDraft(v || "")} height="100%" preview="live" data-color-mode="dark" style={{height: "100%"}}/>
      </div>
    );
  }

  if (file.file_type === "code") {
    const ext = file.name.split(".").pop()?.toLowerCase() || "text";
    const langMap = {py: "python", js: "javascript", jsx: "jsx", ts: "typescript", tsx: "tsx", sh: "bash", json: "json", yaml: "yaml", yml: "yaml", css: "css", html: "markup", sql: "sql"};
    const lang = langMap[ext] || "text";
    return (
      <Highlight theme={themes.vsDark} code={draft} language={lang}>
        {({className, style, tokens, getLineProps, getTokenProps}) => (
          <pre className={cn(className, "m-0 p-4 text-[12px] leading-relaxed")} style={{...style, background: "transparent"}}>
            {tokens.map((line, i) => {
              const lineProps = getLineProps({line});
              return (
                <div key={i} {...lineProps}>
                  <span className="mr-3 inline-block w-8 select-none text-right text-muted-foreground/30">{i + 1}</span>
                  {line.map((token, key) => <span key={key} {...getTokenProps({token})}/>)}
                </div>
              );
            })}
          </pre>
        )}
      </Highlight>
    );
  }

  return <pre className="p-4 text-[12px] leading-relaxed text-muted-foreground/80">{draft}</pre>;
}
