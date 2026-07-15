import { observer } from "mobx-react-lite";
import { useEffect, useState, useCallback } from "react";
import {
    Wrench,
    ChevronLeft,
    ChevronRight,
    ChevronDown,
    FileText,
    FileCode,
    File,
    Folder,
    FolderOpen,
    Loader2,
    Lock,
} from "lucide-react";
import MDEditor from "@uiw/react-md-editor";
import { Highlight, themes } from "prism-react-renderer";

import { cn } from "@/lib/utils";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

/**
 * ToolsView — card grid (builtin + user) → click → file tree + content preview.
 * Builtin tools show metadata only (no files). User tools show file tree.
 */
export const ToolsView = observer(function ToolsView() {
    const [tools, setTools] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState(null);

    useEffect(() => {
        fetch(`${BACKEND}/tools-api`)
            .then((r) => r.json())
            .then((data) => {
                setTools(data);
                setLoading(false);
            })
            .catch(() => setLoading(false));
    }, []);

    if (loading) return <Centered>Loading tools…</Centered>;

    if (selected) {
        return <ToolDetail name={selected} onBack={() => setSelected(null)} />;
    }

    const builtin = tools.filter((t) => t.source === "builtin");
    const user = tools.filter((t) => t.source === "user");

    return (
        <div className="h-full overflow-y-auto">
            <div className="mx-auto max-w-5xl px-6 py-8">
                <div className="mb-6 flex items-center gap-2">
                    <Wrench className="size-5 text-accent" />
                    <h1 className="text-lg font-semibold">Tools</h1>
                    <span className="text-sm text-muted-foreground">
                        ({tools.length})
                    </span>
                </div>

                {builtin.length > 0 && (
                    <>
                        <SectionTitle>Built-in</SectionTitle>
                        <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                            {builtin.map((t) => (
                                <ToolCard
                                    key={t.name}
                                    tool={t}
                                    onClick={() => setSelected(t.name)}
                                />
                            ))}
                        </div>
                    </>
                )}

                {user.length > 0 && (
                    <>
                        <SectionTitle>Custom</SectionTitle>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                            {user.map((t) => (
                                <ToolCard
                                    key={t.name}
                                    tool={t}
                                    onClick={() => setSelected(t.name)}
                                />
                            ))}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
});

// ─── Tool detail ────────────────────────────────────────────────────────────

function ToolDetail({ name, onBack }) {
    const [tree, setTree] = useState(null);
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(true);
    const [expanded, setExpanded] = useState(new Set());
    const [notFound, setNotFound] = useState(false);

    useEffect(() => {
        setLoading(true);
        setNotFound(false);
        fetch(`${BACKEND}/tools-api/${encodeURIComponent(name)}/tree`)
            .then((r) => {
                if (!r.ok) throw new Error("not found");
                return r.json();
            })
            .then((data) => {
                setTree(data);
                const dirs = new Set();
                collectDirs(data, dirs);
                setExpanded(dirs);
                setLoading(false);
                const yaml = findFile(data, "tool.yaml");
                if (yaml) loadFile(yaml.path);
            })
            .catch(() => {
                setNotFound(true);
                setLoading(false);
            });
    }, [name]);

    const loadFile = useCallback(
        async (path) => {
            try {
                const res = await fetch(
                    `${BACKEND}/tools-api/${encodeURIComponent(name)}/file?path=${encodeURIComponent(path)}`
                );
                const f = await res.json();
                setFile(f);
            } catch {
                /* ignore */
            }
        },
        [name]
    );

    const toggleDir = (path) => {
        setExpanded((prev) => {
            const next = new Set(prev);
            if (next.has(path)) next.delete(path);
            else next.add(path);
            return next;
        });
    };

    if (loading)
        return (
            <Centered>
                <Loader2 className="size-4 animate-spin" /> Loading…
            </Centered>
        );

    // Builtin tool: no files, show metadata only
    if (notFound) {
        return (
            <div className="flex h-full">
                <div className="flex w-60 shrink-0 flex-col border-r border-border/60 bg-sidebar/20">
                    <button
                        onClick={onBack}
                        className="flex items-center gap-1 px-4 py-3 text-sm text-muted-foreground transition hover:text-foreground"
                    >
                        <ChevronLeft className="size-4" /> Tools
                    </button>
                    <div className="px-4 py-2">
                        <div className="flex items-center gap-2">
                            <div className="flex size-8 items-center justify-center rounded-lg bg-accent/10">
                                <Lock className="size-4 text-muted-foreground/50" />
                            </div>
                            <span className="text-sm font-medium">{name}</span>
                        </div>
                    </div>
                </div>
                <div className="flex flex-1 items-center justify-center">
                    <div className="text-center">
                        <Lock className="mx-auto mb-3 size-8 text-muted-foreground/30" />
                        <p className="text-sm text-muted-foreground">
                            Built-in tool — no source files to browse.
                        </p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex h-full">
            <div className="flex w-60 shrink-0 flex-col border-r border-border/60 bg-sidebar/20">
                <button
                    onClick={onBack}
                    className="flex items-center gap-1 px-4 py-3 text-sm text-muted-foreground transition hover:text-foreground"
                >
                    <ChevronLeft className="size-4" /> Tools
                </button>
                <div className="px-4 py-2">
                    <div className="flex items-center gap-2">
                        <div className="flex size-8 items-center justify-center rounded-lg bg-accent/10">
                            <Wrench className="size-4 text-accent" />
                        </div>
                        <span className="text-sm font-medium">{name}</span>
                    </div>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
                    {tree && (
                        <TreeNode
                            node={tree}
                            expanded={expanded}
                            toggleDir={toggleDir}
                            onSelect={loadFile}
                            selectedPath={file?.path}
                            depth={0}
                        />
                    )}
                </div>
            </div>

            <div className="min-h-0 flex-1 overflow-hidden">
                <div className="flex h-full flex-col">
                    {file ? (
                        <>
                            <div className="shrink-0 border-b border-border/60 px-4 py-2 text-[12px] text-muted-foreground">
                                {file.name}
                            </div>
                            <div
                                className="min-h-0 flex-1 overflow-auto"
                                data-color-mode="dark"
                            >
                                <FileContent file={file} />
                            </div>
                        </>
                    ) : (
                        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                            Select a file to view
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

// ─── Shared components (same as SkillsView) ─────────────────────────────────

function TreeNode({
    node,
    expanded,
    toggleDir,
    onSelect,
    selectedPath,
    depth,
}) {
    const isDir = node.type === "dir";
    const isOpen = expanded.has(node.path);

    if (depth === 0 && isDir) {
        return (
            <div>
                {node.children.map((child) => (
                    <TreeNode
                        key={child.path || child.name}
                        node={child}
                        expanded={expanded}
                        toggleDir={toggleDir}
                        onSelect={onSelect}
                        selectedPath={selectedPath}
                        depth={1}
                    />
                ))}
            </div>
        );
    }

    return (
        <div>
            <button
                onClick={() =>
                    isDir ? toggleDir(node.path) : onSelect(node.path)
                }
                className={cn(
                    "flex w-full items-center gap-1 rounded-md px-2 py-1 text-[12px] transition",
                    !isDir && selectedPath === node.path
                        ? "bg-accent/10 text-accent"
                        : "text-muted-foreground hover:bg-sidebar/40 hover:text-foreground"
                )}
                style={{ paddingLeft: `${depth * 12 + 8}px` }}
            >
                {isDir ? (
                    <>
                        {isOpen ? (
                            <ChevronDown className="size-3 shrink-0" />
                        ) : (
                            <ChevronRight className="size-3 shrink-0" />
                        )}
                        {isOpen ? (
                            <FolderOpen className="size-3 shrink-0 text-muted-foreground/60" />
                        ) : (
                            <Folder className="size-3 shrink-0 text-muted-foreground/60" />
                        )}
                    </>
                ) : (
                    <>
                        <span className="w-3 shrink-0" />
                        <FileIcon name={node.name} />
                    </>
                )}
                <span className="truncate">{node.name}</span>
            </button>
            {isDir &&
                isOpen &&
                node.children.map((child) => (
                    <TreeNode
                        key={child.path || child.name}
                        node={child}
                        expanded={expanded}
                        toggleDir={toggleDir}
                        onSelect={onSelect}
                        selectedPath={selectedPath}
                        depth={depth + 1}
                    />
                ))}
        </div>
    );
}

function FileIcon({ name }) {
    const ext = name.split(".").pop()?.toLowerCase();
    if (ext === "md")
        return <FileText className="size-3 shrink-0 text-accent/60" />;
    if (
        [
            "py",
            "js",
            "jsx",
            "ts",
            "tsx",
            "sh",
            "json",
            "yaml",
            "yml",
            "css",
        ].includes(ext)
    )
        return (
            <FileCode className="size-3 shrink-0 text-muted-foreground/50" />
        );
    return <File className="size-3 shrink-0 text-muted-foreground/40" />;
}

function FileContent({ file }) {
    if (file.file_type === "markdown") {
        return (
            <div className="h-full" data-color-mode="dark">
                <MDEditor
                    value={file.content}
                    height="100%"
                    preview="live"
                    data-color-mode="dark"
                    style={{ height: "100%" }}
                />
            </div>
        );
    }
    if (file.file_type === "code") {
        const ext = file.name.split(".").pop()?.toLowerCase() || "text";
        const langMap = {
            py: "python",
            js: "javascript",
            jsx: "jsx",
            ts: "typescript",
            tsx: "tsx",
            sh: "bash",
            json: "json",
            yaml: "yaml",
            yml: "yaml",
            css: "css",
        };
        const lang = langMap[ext] || "text";
        return (
            <Highlight
                theme={themes.vsDark}
                code={file.content}
                language={lang}
            >
                {({
                    className,
                    style,
                    tokens,
                    getLineProps,
                    getTokenProps,
                }) => (
                    <pre
                        className={cn(
                            className,
                            "m-0 p-4 text-[12px] leading-relaxed"
                        )}
                        style={{ ...style, background: "transparent" }}
                    >
                        {tokens.map((line, i) => {
                            const lineProps = getLineProps({ line });
                            return (
                                <div key={i} {...lineProps}>
                                    <span className="mr-3 inline-block w-8 select-none text-right text-muted-foreground/30">
                                        {i + 1}
                                    </span>
                                    {line.map((token, key) => (
                                        <span
                                            key={key}
                                            {...getTokenProps({ token })}
                                        />
                                    ))}
                                </div>
                            );
                        })}
                    </pre>
                )}
            </Highlight>
        );
    }
    return (
        <pre className="p-4 text-[12px] leading-relaxed text-muted-foreground/80">
            {file.content}
        </pre>
    );
}

function ToolCard({ tool, onClick }) {
    return (
        <button
            onClick={onClick}
            className="group rounded-xl border border-border/60 bg-card p-4 text-left transition hover:border-accent/40 hover:bg-sidebar/30"
        >
            <div className="mb-3 flex items-center gap-3">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent/10">
                    {tool.source === "builtin" ? (
                        <Lock className="size-4 text-muted-foreground/50" />
                    ) : (
                        <Wrench className="size-5 text-accent" />
                    )}
                </div>
                <div className="min-w-0">
                    <div className="flex items-center gap-1">
                        <span className="truncate text-sm font-medium">
                            {tool.name}
                        </span>
                    </div>
                    <div className="mt-0.5">
                        <span
                            className={cn(
                                "rounded-sm px-1.5 py-0.5 text-[9px]",
                                tool.source === "user"
                                    ? "bg-accent/10 text-accent"
                                    : "bg-muted/20 text-muted-foreground"
                            )}
                        >
                            {tool.source}
                        </span>
                    </div>
                </div>
            </div>
            <p className="line-clamp-2 text-[11px] text-muted-foreground/70">
                {tool.description || "(no description)"}
            </p>
        </button>
    );
}

function SectionTitle({ children }) {
    return (
        <div className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/60">
            {children}
        </div>
    );
}

function collectDirs(node, dirs) {
    if (node.type === "dir") {
        dirs.add(node.path);
        for (const child of node.children || []) collectDirs(child, dirs);
    }
}

function findFile(node, name) {
    if (node.type === "file" && node.name === name) return node;
    for (const child of node.children || []) {
        const found = findFile(child, name);
        if (found) return found;
    }
    return null;
}

function Centered({ children }) {
    return (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {children}
        </div>
    );
}
