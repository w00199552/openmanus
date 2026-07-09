import {createContext, useContext} from "react";

import {rootStore} from "@/stores";

/**
 * React binding for the mobx RootStore singleton.
 *
 * Components read state via `useStore()` and call store/runtime *actions*;
 * the message stream comes from the multi-agent runtime (agentRuntime), an
 * observable data source rendered by ThreadView.
 */
const StoreContext = createContext(rootStore);

export function StoreProvider({ children }) {
  return (
    <StoreContext.Provider value={rootStore}>{children}</StoreContext.Provider>
  );
}

export function useStore() {
  return useContext(StoreContext);
}
