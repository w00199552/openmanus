import { createContext, useContext } from "react";

/**
 * PlaygroundContext — bridges the shell's toolbar RIGHT slot to whatever tool
 * is currently mounted.
 *
 * The shell owns the toolbar DOM; the active tool owns its own actions state
 * (file name, Save button, etc.). Rather than lift each tool's state up to
 * the shell (which would couple the shell to every tool's internals), the
 * shell publishes a ref to its toolbar-right <div> through this context.
 * Any tool can then `createPortal(<Actions/>, toolbarRightRef.current)` to
 * paint its contextual actions into the toolbar — keeping state local to the
 * tool while the toolbar stays visually unified.
 *
 * The value is a React ref object (MutableRefObject<HTMLDivElement | null>).
 * Tools should guard against `.current` being null on first paint.
 */
export const PlaygroundContext = createContext({ current: null });

export function usePlaygroundToolbar() {
    return useContext(PlaygroundContext);
}
