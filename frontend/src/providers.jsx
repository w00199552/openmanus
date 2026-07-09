import {Fragment} from "react";

/**
 * App providers.
 *
 * CopilotKit was removed (path 2): chat is now driven by direct AG-UI SSE
 * from the Python backend (see agentService.js + ChatStore.js). This wrapper
 * is kept as a no-op so main.jsx's tree shape stays stable.
 */
const AppProviders = function AppProviders({ children }) {
  return <Fragment>{children}</Fragment>;
};

export { AppProviders };
