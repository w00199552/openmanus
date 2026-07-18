/**
 * SandboxStore — owns the Sandbox panel's entire state + operations.
 *
 * Single source of truth for:
 *   - workdir (the active session's working directory)
 *   - cd command (API call + workdir update)
 *   - file CRUD (tree, read, write, lazy children)
 *
 * Injected into RootStore alongside AgentRuntime.  The runtime delegates
 * cd commands here; Playground reads workdir and calls file methods here.
 *
 * @module stores/SandboxStore
 */

import { makeAutoObservable, runInAction } from "mobx";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

export class SandboxStore {
    // ─── injected collaborators ──────────────────────────────────────────────
    _sessionStore = null;

    // ─── observable state ───────────────────────────────────────────────────
    /** Current workdir (synced from session on switch, updated by cd). */
    workdir = "";

    constructor() {
        makeAutoObservable(this);
    }

    setSessionStore(s) {
        this._sessionStore = s;
    }

    // ─── workdir sync ────────────────────────────────────────────────────────

    /**
     * Sync workdir from a session row (called when the user switches session).
     * Reads `sess.workdir` from the SessionStore and copies it into our
     * observable — no API call needed.
     */
    syncFromSession(sessionId) {
        if (!this._sessionStore) return;
        const sess = this._sessionStore.sessions.find(
            (s) => s.id === sessionId
        );
        if (sess && sess.workdir) {
            this.workdir = sess.workdir;
        }
    }

    // ─── cd command ──────────────────────────────────────────────────────────

    /**
     * Execute a cd command: call the backend API, update workdir + session row.
     * Returns `{workdir, action}` so the caller can display a system message.
     * Throws on error.
     */
    async cd(sessionId, path) {
        const res = await fetch(
            `${BACKEND}/sessions/${encodeURIComponent(sessionId)}/cd`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path }),
            }
        );
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `cd failed: ${res.status}`);
        }
        const body = await res.json();

        if (body.workdir && body.action === "cd") {
            runInAction(() => {
                this.workdir = body.workdir;
                if (this._sessionStore) {
                    const sess = this._sessionStore.sessions.find(
                        (s) => s.id === sessionId
                    );
                    if (sess) sess.workdir = body.workdir;
                }
            });
        }

        return body; // {workdir, action}
    }

    // ─── file operations ─────────────────────────────────────────────────────

    /** GET /files/tree — root + first-level children (collapsed dirs). */
    async loadTree() {
        const wdParam = this.workdir
            ? `?workdir=${encodeURIComponent(this.workdir)}`
            : "";
        const res = await fetch(`${BACKEND}/files/tree${wdParam}`);
        if (!res.ok) throw new Error(`tree failed: ${res.status}`);
        return res.json();
    }

    /** GET /files/children — immediate children of a dir (lazy expansion). */
    async loadChildren(dirPath) {
        const wdParam = this.workdir
            ? `&workdir=${encodeURIComponent(this.workdir)}`
            : "";
        const res = await fetch(
            `${BACKEND}/files/children?path=${encodeURIComponent(dirPath)}${wdParam}`
        );
        if (!res.ok) throw new Error(`children failed: ${res.status}`);
        const data = await res.json();
        return data.children;
    }

    /** GET /files/read — read a file's content. */
    async loadFile(path) {
        const wdParam = this.workdir
            ? `&workdir=${encodeURIComponent(this.workdir)}`
            : "";
        const res = await fetch(
            `${BACKEND}/files/read?path=${encodeURIComponent(path)}${wdParam}`
        );
        if (!res.ok) throw new Error(`read failed: ${res.status}`);
        return res.json();
    }

    /** PUT /files/write — save a file. */
    async saveFile(path, content) {
        const res = await fetch(`${BACKEND}/files/write`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                path,
                content,
                workdir: this.workdir || undefined,
            }),
        });
        if (!res.ok) throw new Error(`write failed: ${res.status}`);
        return res.json();
    }

    /** DELETE /files/delete — delete a file or directory. */
    async deletePath(path) {
        const res = await fetch(`${BACKEND}/files/delete`, {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path, workdir: this.workdir || undefined }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `delete failed: ${res.status}`);
        }
        return res.json();
    }

    /** POST /files/mkdir — create a directory. */
    async createDir(path) {
        const res = await fetch(`${BACKEND}/files/mkdir`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path, workdir: this.workdir || undefined }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `mkdir failed: ${res.status}`);
        }
        return res.json();
    }

    /** POST /files/create — create an empty file. */
    async createFile(path) {
        const res = await fetch(`${BACKEND}/files/create`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path, workdir: this.workdir || undefined }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `create failed: ${res.status}`);
        }
        return res.json();
    }

    /** Build the watchdog SSE URL for the current workdir. */
    get watchUrl() {
        const wdParam = this.workdir
            ? `?workdir=${encodeURIComponent(this.workdir)}`
            : "";
        return `${BACKEND}/files/watch${wdParam}`;
    }
}
