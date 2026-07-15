import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge tailwind classes with conditional logic (shadcn standard helper). */
export function cn(...inputs) {
    return twMerge(clsx(inputs));
}

/**
 * Join a workdir with a POSIX-style relative path (as returned by the files
 * API, e.g. "dir/sub/file") into an absolute OS path. The separator is
 * inferred from the workdir so Windows backslash workdirs stay consistent.
 * An empty `relPath` returns the workdir untouched (tree root).
 */
export function joinAbsPath(workdir, relPath) {
    if (!relPath) return workdir;
    const sep = workdir.includes("\\") ? "\\" : "/";
    const rel = relPath.split("/").filter(Boolean).join(sep);
    return `${workdir}${sep}${rel}`;
}

/**
 * Copy text to the clipboard, falling back to a hidden <textarea> +
 * execCommand for non-secure contexts (e.g. Electron file://). Resolves to
 * whether the copy succeeded.
 */
export async function copyText(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch {
        // fall through to legacy path
    }
    try {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.top = "-9999px";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(ta);
        return ok;
    } catch {
        return false;
    }
}
