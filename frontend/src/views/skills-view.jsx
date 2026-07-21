import { observer } from "mobx-react-lite";
import { useEffect, useState, useCallback } from "react";
import {
    Sparkles,
    ChevronLeft,
    ChevronRight,
    ChevronDown,
    FileText,
    FileCode,
    File,
    Folder,
    FolderOpen,
    Loader2,
} from "lucide-react";
import MDEditor from "@uiw/react-md-editor";
import { Highlight, themes } from "prism-react-renderer";

import { useStore } from "@/hooks/use-store";
import {
    listSkills,
    getSkillTree,
    getSkillFile,
} from "@/services/agent-service";
import { cn } from "@/lib/utils";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

/**
 * SkillsView — card grid → click → file tree + content preview.
 */
export const SkillsView = observer(function SkillsView() {
    const { skillStore } = useStore();
    const [selected, setSelected] = useState(null);

    useEffect(() => {
        skillStore.loadSkills();
    }, [skillStore]);

    if (selected) {
        return <SkillDetail name={selected} onBack={() => setSelected(null)} />;
    }

    if (skillStore.loading) return <Centered>Loading skills…</Centered>;

    return (
        <div className="h-full overflow-y-auto">
            <div className="mx-auto max-w-5xl px-6 py-8">
                <div className="mb-6 flex items-center gap-2.5">
                    <span className="flex size-8 items-center justify-center rounded-lg bg-foreground/5 ring-1 ring-border/60">
                        <Sparkles className="size-4 text-foreground/70" />
                    </span>
                    <h1 className="h-display">Skills</h1>
                    <span className="text-sm text-muted-foreground">
                        ({skillStore.skills.length})
                    </span>
                </div>

                {skillStore.skills.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-border/40 p-12 text-center">
                        <Sparkles className="mx-auto mb-3 size-8 text-muted-foreground/30" />
                        <p className="text-sm text-muted-foreground">
                            No skills installed.
                        </p>
                        <p className="mt-1 text-[12px] text-muted-foreground/60">
                            Copy skill directories to ~/.openmanus/skills/
                        </p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                        {skillStore.skills.map((s) => (
                            <SkillCard
                                key={s.name}
                                skill={s}
                                onClick={() => setSelected(s.name)}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
});

// ─── Skill detail: file tree + content ──────────────────────────────────────

function SkillDetail({ name, onBack }) {
    const [tree, setTree] = useState(null);
    const [file, setFile] = useState(null); // {path, content, file_type}
    const [loading, setLoading] = useState(true);
    const [expanded, setExpanded] = useState(new Set());

    useEffect(() => {
        setLoading(true);
        getSkillTree(name)
            .then((data) => {
                setTree(data);
                // auto-expand root + expand first dir level
                const dirs = new Set();
                collectDirs(data, dirs);
                setExpanded(dirs);
                setLoading(false);
                // auto-select SKILL.md
                const skillMd = findFile(data, "SKILL.md");
                if (skillMd) loadFile(skillMd.path);
            })
            .catch(() => setLoading(false));
    }, [name]);

    const loadFile = useCallback(
        async (path) => {
            try {
                const f = await getSkillFile(name, path);
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

    return (
        <div className="flex h-full">
            {/* left: file tree */}
            <div className="flex w-56 shrink-0 flex-col border-r border-border/60 bg-sidebar/20">
                <button
                    onClick={onBack}
                    className="flex items-center gap-1 px-4 py-3 text-sm text-muted-foreground transition hover:bg-foreground/5 hover:text-foreground"
                >
                    <ChevronLeft className="size-4" /> Skills
                </button>
                <div className="px-4 py-2">
                    <div className="flex items-center gap-2">
                        <div className="flex size-8 items-center justify-center rounded-lg bg-foreground/5 ring-1 ring-border/60">
                            <Sparkles className="size-4 text-foreground/70" />
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

            {/* right: file content */}
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

// ─── Tree node (recursive) ──────────────────────────────────────────────────

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

    // Root node: render children directly (no indent)
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
        return <FileText className="size-3 shrink-0 text-muted-foreground/60" />;
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

// ─── File content renderer ──────────────────────────────────────────────────

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
            html: "markup",
            sql: "sql",
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

    // plain text
    return (
        <pre className="p-4 text-[12px] leading-relaxed text-muted-foreground/80">
            {file.content}
        </pre>
    );
}

// ─── Card + helpers ─────────────────────────────────────────────────────────

function SkillCard({ skill, onClick }) {
    return (
        <button
            onClick={onClick}
            className="rounded-card group p-6 text-left"
        >
            <div className="mb-4 flex items-center gap-3">
                <div className="card-icon-badge size-12 shrink-0">
                    <Sparkles className="size-5" />
                </div>
                <div className="min-w-0">
                    <span className="truncate font-display text-xl font-medium tracking-tight">
                        {skill.name}
                    </span>
                    <div className="mt-0.5 flex gap-1">
                        {skill.has_scripts && (
                            <span className="rounded-sm bg-foreground/10 px-1.5 py-0.5 text-[9px] text-muted-foreground">
                                scripts
                            </span>
                        )}
                        {skill.has_references && (
                            <span className="rounded-sm bg-foreground/8 px-1.5 py-0.5 text-[9px] text-muted-foreground">
                                refs
                            </span>
                        )}
                    </div>
                </div>
            </div>
            <p className="line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">
                {skill.description || "(no description)"}
            </p>
        </button>
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
