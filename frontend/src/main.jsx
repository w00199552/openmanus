import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppProviders } from "@/providers";
import { StoreProvider } from "@/hooks/useStore";
import App from "./App.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(
    <StrictMode>
        <AppProviders>
            <StoreProvider>
                <App />
            </StoreProvider>
        </AppProviders>
    </StrictMode>
);
