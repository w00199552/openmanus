import { Highlight, themes } from "prism-react-renderer";

// Static sample content for the placeholder IDE tab.
const SAMPLE = `# Manus playground — code editor (placeholder)
#
# This surface will be driven by agents (via CopilotKit frontendTool):
# a "Coder" sub-agent writes/edits files here, and you watch it live.

def greet(name: str) -> str:
    return f"Hello, {name}! I'm Manus."


if __name__ == "__main__":
    print(greet("world"))
`;

/**
 * CodeEditor — a lightweight code surface in the Playground.
 *
 * Placeholder for now (static Python sample with syntax highlighting via
 * prism-react-renderer — lighter than Monaco so it works everywhere).
 * Later, agents will write to it via CopilotKit frontendTool.
 */
export function CodeEditor() {
    return (
        <div className="h-full overflow-auto bg-background p-3 font-mono text-[12px] leading-relaxed">
            <Highlight
                theme={themes.vsDark}
                code={SAMPLE.trim()}
                language="python"
            >
                {({
                    className,
                    style,
                    tokens,
                    getLineProps,
                    getTokenProps,
                }) => (
                    <pre
                        className={className}
                        style={{ ...style, background: "transparent" }}
                    >
                        {tokens.map((line, i) => {
                            const lineProps = getLineProps({ line });
                            return (
                                <div
                                    key={i}
                                    {...lineProps}
                                    className={
                                        lineProps.className + " table-row"
                                    }
                                >
                                    <span className="table-cell w-8 select-none pr-3 text-right text-muted-foreground/40">
                                        {i + 1}
                                    </span>
                                    <span className="table-cell">
                                        {line.map((token, key) => {
                                            const tokenProps = getTokenProps({
                                                token,
                                            });
                                            return (
                                                <span
                                                    key={key}
                                                    {...tokenProps}
                                                />
                                            );
                                        })}
                                    </span>
                                </div>
                            );
                        })}
                    </pre>
                )}
            </Highlight>
        </div>
    );
}
