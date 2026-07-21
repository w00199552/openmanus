import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppProviders } from "@/providers";
import { StoreProvider } from "@/hooks/use-store";
import App from "./app.jsx";
import "./index.css";

// Apply the theme BEFORE React renders to avoid a flash of the wrong theme.
// Mirrors the logic in use-theme.js: read stored mode, resolve system, toggle
// .dark on <html>. Kept inline (not imported) so it runs synchronously at
// module-eval time with zero chance of an import-order race.
(function applyInitialTheme() {
    try {
        const stored = localStorage.getItem("openmanus.theme");
        const mode =
            stored === "dark" || stored === "light" || stored === "system"
                ? stored
                : "dark"; // default dark-first
        const isDark =
            mode === "system"
                ? window.matchMedia?.("(prefers-color-scheme: dark)").matches ??
                  true
                : mode === "dark";
        document.documentElement.classList.toggle("dark", isDark);
    } catch {
        document.documentElement.classList.add("dark");
    }
})();

createRoot(document.getElementById("root")).render(
    <StrictMode>
        <AppProviders>
            <StoreProvider>
                <App />
            </StoreProvider>
        </AppProviders>
    </StrictMode>
);
