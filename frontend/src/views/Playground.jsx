import {useState, useEffect, useCallback} from "react";
import {observer} from "mobx-react-lite";
import {
  ChevronRight, ChevronDown, FileText, FileCode, File, Folder, FolderOpen,
  Save, RefreshCw, Loader2, FolderTree,
} from "lucide-react";
import MDEditor from "@uiw/react-md-editor";
import {Highlight, themes} from "prism-react-renderer";
import {Group, Panel, Separator} from "react-resizable-panels";

import {useStore} from "@/hooks/useStore";
import {cn} from "@/lib/utils";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

/**
 * Playground — file tree + content editor for the workdir.
 *
 * Tree: depth=1 on load (collapsed dirs); children are lazy-loaded on
 * first expand via GET /files/children.
 *
 * Right: file content (markdown editor / code viewer / text).
 * Live refresh: watches /files/watch SSE for external changes.
 * Save: PUT /files/write.
 */
export const Playground = observer(function Playground() {
  const {runtime} = useStore();
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

  const loadTree = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND}/files/tree`);
      if (!res.ok) return;
      const data = await res.json();
      setTree(data);
      // collapse all dirs by default
      setExpanded(new Set());
      setChildrenByDir({});
      setLoadingByDir(new Set());
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  const loadChildren = useCallback(async (dirPath) => {
    // already loaded
    if (childrenByDir[dirPath]) return;
    setLoadingByDir((prev) => new Set(prev).add(dirPath));
    try {
      const res = await fetch(`${BACKEND}/files/children?path=${encodeURIComponent(dirPath)}`);
      if (!res.ok) return;
      const data = await res.json();
      setChildrenByDir((prev) => ({...prev, [dirPath]: data.children}));
    } catch { /* ignore */ }
    finally {
      setLoadingByDir((prev) => {
        const next = new Set(prev);
        next.delete(dirPath);
        return next;
      });
    }
  }, [childrenByDir]);

  const loadFile = useCallback(async (path) => {
    try {
      const res = await fetch(`${BACKEND}/files/read?path=${encodeURIComponent(path)}`);
      if (!res.ok) return;
      const data = await res.json();
      setFile(data);
      setDraft(data.content);
      setDirty(false);
    } catch { /* ignore */ }
  }, []);

  const saveFile = useCallback(async () => {
    if (!file || !dirty) return;
    setSaving(true);
    try {
      await fetch(`${BACKEND}/files/write`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path: file.path, content: draft}),
      });
      setDirty(false);
    } catch { /* ignore */ }
    setSaving(false);
  }, [file, draft, dirty]);

  // initial load
  useEffect(() => {
    loadTree();
  }, [loadTree]);

  // watch runtime.workdir for cd changes (mobx observer auto-triggers)
  useEffect(() => {
    if (runtime.workdir) {
      loadTree();
      setFile(null);
    }
  }, [runtime.workdir, loadTree]);

  // watchdog: live refresh
  useEffect(() => {
    const es = new EventSource(`${BACKEND}/files/watch`);
    es.onmessage = (ev) => {
      try {
        const evt = JSON.parse(ev.data);
        if (evt.type === "ping") return;
        // refresh tree on any structural change
        if (evt.type === "created" || evt.type === "deleted" || evt.type === "moved") {
          loadTree();
        }
        // refresh open file if it was modified externally
        if (evt.type === "modified" && file && evt.path === file.path && !dirty) {
          loadFile(file.path);
        }
      } catch { /* ignore */ }
    };
    return () => es.close();
  }, [loadTree, loadFile, file, dirty]);

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
            {runtime.workdir && (
              <div className="flex shrink-0 items-center gap-1.5 border-b border-border/40 px-3 py-1.5" title={runtime.workdir}>
                <FolderTree className="size-3.5 shrink-0 text-sky-400/70"/>
                <span className="truncate text-[11px] font-medium text-foreground/80">{runtime.workdir}</span>
              </div>
            )}
            <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
              {tree && (
                <TreeNode node={tree} expanded={expanded} toggleDir={toggleDir} onSelect={onSelectFile} selectedPath={file?.path} depth={0} childrenByDir={childrenByDir} loadingByDir={loadingByDir}/>
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
    </div>
  );
});

// ─── Tree node (recursive, lazy) ─────────────────────────────────────────────

function TreeNode({node, expanded, toggleDir, onSelect, selectedPath, depth, childrenByDir, loadingByDir}) {
  const isDir = node.type === "dir";
  const isOpen = expanded.has(node.path);
  const isLoading = loadingByDir.has(node.path);
  // lazy-loaded children for this dir (if expanded); root uses built-in children
  const children = depth === 0
    ? (node.children || [])
    : (isDir ? (childrenByDir[node.path] || null) : null);

  // root: render children only
  if (depth === 0 && isDir) {
    return (
      <div>
        {(node.children || []).map((child) => (
          <TreeNode key={child.path || child.name} node={child} expanded={expanded} toggleDir={toggleDir} onSelect={onSelect} selectedPath={selectedPath} depth={1} childrenByDir={childrenByDir} loadingByDir={loadingByDir}/>
        ))}
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={() => isDir ? toggleDir(node.path) : onSelect(node.path)}
        className={cn(
          "flex w-full items-center gap-1 rounded-md px-2 py-1 text-[12px] transition",
          !isDir && selectedPath === node.path
            ? "bg-accent/10 text-accent"
            : "text-muted-foreground/90 hover:bg-sidebar/40 hover:text-foreground",
        )}
        style={{paddingLeft: `${depth * 12 + 4}px`}}
      >
        {isDir ? (
          <>
            {isLoading ? (
              <Loader2 className="size-3 shrink-0 animate-spin text-muted-foreground/50"/>
            ) : (
              isOpen ? <ChevronDown className="size-3 shrink-0"/> : <ChevronRight className="size-3 shrink-0"/>
            )}
            {isOpen ? <FolderOpen className="size-3 shrink-0 text-sky-400/70"/> : <Folder className="size-3 shrink-0 text-sky-400/70"/>}
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
            <TreeNode key={child.path || child.name} node={child} expanded={expanded} toggleDir={toggleDir} onSelect={onSelect} selectedPath={selectedPath} depth={depth + 1} childrenByDir={childrenByDir} loadingByDir={loadingByDir}/>
          ))
      )}
    </div>
  );
}

function FileIcon({name}) {
  const ext = name.split(".").pop()?.toLowerCase();
  if (ext === "md") return <FileText className="size-3 shrink-0 text-accent/60"/>;
  if (["py", "js", "jsx", "ts", "tsx", "sh", "json", "yaml", "yml", "css"].includes(ext)) return <FileCode className="size-3 shrink-0 text-muted-foreground/50"/>;
  return <File className="size-3 shrink-0 text-muted-foreground/40"/>;
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
