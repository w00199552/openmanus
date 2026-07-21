import { useCallback, useEffect, useState } from "react";

/**
 * Theme management for the OpenManus frontend.
 *
 * Strategy: a `.dark` class on <html> toggles between the light tokens (in
 * :root) and the dark tokens (in .dark). Tailwind v4's `dark:` variant is
 * configured to follow the same class, so both CSS variables and dark:
 * utilities stay in sync.
 *
 * Three mode values: "dark" | "light" | "system".
 *   - "system" resolves via prefers-color-scheme and live-follows OS changes.
 *   - explicit dark/light wins over system and is persisted to localStorage.
 *
 * The initial class is applied SYNCHRONOUSLY in main.jsx (before React
 * renders) to prevent a flash of the wrong theme (FOUC). This hook reads that
 * pre-applied state on mount so the first render matches the DOM.
 */

const STORAGE_KEY = "openmanus.theme";

function readStoredMode() {
    if (typeof window === "undefined") return "dark";
    try {
        const v = window.localStorage.getItem(STORAGE_KEY);
        if (v === "dark" || v === "light" || v === "system") return v;
    } catch {
        /* ignore */
    }
    return "dark"; // default — dark-first, per product decision
}

function systemPrefersDark() {
    if (typeof window === "undefined" || !window.matchMedia) return true;
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveDark(mode) {
    if (mode === "dark") return true;
    if (mode === "light") return false;
    return systemPrefersDark(); // "system"
}

function applyDark(isDark) {
    if (typeof document === "undefined") return;
    document.documentElement.classList.toggle("dark", isDark);
}

/**
 * useTheme — read + control the active theme mode.
 *
 * Returns:
 *   mode: "dark" | "light" | "system"   — the user's CHOICE (what's stored)
 *   isDark: boolean                      — the RESOLVED effective theme
 *   setMode(next): void                  — change the choice + persist
 *   toggle(): void                       — flip between dark & light (skips system)
 *
 * The hook is intentionally framework-light (no context provider): state is
 * module-local + synchronized across instances via the storage event. In
 * practice we only call it once (in TopNav), so this is plenty.
 */
export function useTheme() {
    const [mode, setModeState] = useState(readStoredMode);
    const [isDark, setIsDark] = useState(() => resolveDark(readStoredMode()));

    // Apply + sync whenever mode changes.
    useEffect(() => {
        const dark = resolveDark(mode);
        applyDark(dark);
        setIsDark(dark);
    }, [mode]);

    // When mode is "system", live-follow OS theme changes.
    useEffect(() => {
        if (mode !== "system") return;
        const mq = window.matchMedia("(prefers-color-scheme: dark)");
        const onChange = () => {
            const dark = mq.matches;
            applyDark(dark);
            setIsDark(dark);
        };
        mq.addEventListener("change", onChange);
        return () => mq.removeEventListener("change", onChange);
    }, [mode]);

    // Keep in sync if another tab changes the theme (storage event).
    useEffect(() => {
        const onStorage = (e) => {
            if (e.key === STORAGE_KEY) setModeState(readStoredMode());
        };
        window.addEventListener("storage", onStorage);
        return () => window.removeEventListener("storage", onStorage);
    }, []);

    const setMode = useCallback((next) => {
        setModeState(next);
        try {
            window.localStorage.setItem(STORAGE_KEY, next);
        } catch {
            /* ignore */
        }
    }, []);

    const toggle = useCallback(() => {
        // Toggle between explicit dark/light — once the user clicks, they've
        // taken control, so we leave "system" mode behind.
        setModeState((prev) => {
            const currentlyDark = resolveDark(prev);
            const next = currentlyDark ? "light" : "dark";
            try {
                window.localStorage.setItem(STORAGE_KEY, next);
            } catch {
                /* ignore */
            }
            return next;
        });
    }, []);

    return { mode, isDark, setMode, toggle };
}
