import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Highlight, themes } from "prism-react-renderer";
import { Check, ClipboardCopy } from "lucide-react";

import { cn, copyText } from "@/lib/utils";
import { useTheme } from "@/hooks/use-theme";

/**
 * MarkdownText — renders assistant message content as GitHub-flavored markdown.
 *
 * Built on react-markdown + remark-gfm. Each element is styled to match the
 * openmanus design system (no Tailwind typography plugin — we map elements
 * by hand so the look stays consistent with the rest of the app):
 *   - code blocks: prism-react-renderer vsDark (same theme as the Sandbox
 *     file editor), with a header bar + copy button
 *   - inline code: lime-tinted pill
 *   - links: accent color, underline on hover
 *   - headings: ClashDisplay, devraj-style weight 500
 *   - lists, tables, quotes: hairline borders, generous spacing
 *
 * Streaming-safe: if the markdown is mid-stream (incomplete fence, unclosed
 * bracket), react-markdown degrades gracefully to text — and we wrap the
 * whole render in a try/catch via the component tree so a parse hiccup never
 * throws off the chat thread.
 *
 * @param {{ content: string, className?: string }} props
 */
export function MarkdownText({ content, className }) {
    return (
        <div
            className={cn(
                "text-[14px] leading-relaxed text-foreground",
                // block-level spacing: every direct child block gets vertical
                // rhythm except the first one (no top margin on opening block).
                "[&_>*:first-child]:mt-0 [&_>*:last-child]:mb-0",
                "[&_>*]:mt-3 [&_>*]:mb-0",
                className
            )}
        >
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                    // Headings — ClashDisplay, weight 500, tight leading.
                    h1: (props) => (
                        <h1
                            className="font-display mt-6 text-[22px] font-medium tracking-tight"
                            {...props}
                        />
                    ),
                    h2: (props) => (
                        <h2
                            className="font-display mt-5 text-[19px] font-medium tracking-tight"
                            {...props}
                        />
                    ),
                    h3: (props) => (
                        <h3
                            className="font-display mt-4 text-[16px] font-medium tracking-tight"
                            {...props}
                        />
                    ),
                    h4: (props) => (
                        <h4 className="mt-4 text-[14px] font-semibold" {...props} />
                    ),
                    h5: (props) => (
                        <h5 className="mt-3 text-[13px] font-semibold" {...props} />
                    ),
                    h6: (props) => (
                        <h6 className="mt-3 text-[12px] font-semibold uppercase tracking-wider text-muted-foreground" {...props} />
                    ),

                    // Paragraph — just inherit the container's text style.
                    p: (props) => <p {...props} />,

                    // Strong / emphasis.
                    strong: (props) => (
                        <strong className="font-semibold text-foreground" {...props} />
                    ),
                    em: (props) => <em className="italic" {...props} />,

                    // Inline link — accent, underline on hover.
                    a: ({ node, ...props }) => (
                        <a
                            className="text-accent underline decoration-accent/40 underline-offset-2 transition hover:decoration-accent"
                            target="_blank"
                            rel="noreferrer noopener"
                            {...props}
                        />
                    ),

                    // Inline code — lime-tinted pill, monospace.
                    // (Code BLOCKS are handled by the `code` component below by
                    // checking for a language or newline.)
                    code: ({ node, className: cls, children, ...props }) => {
                        const text = String(children ?? "");
                        // react-markdown v9 passes fenced code blocks here with a
                        // `language-xxx` class. Inline code has no such class and
                        // no newline in its text.
                        const isBlock =
                            /language-/.test(cls || "") || text.includes("\n");
                        if (isBlock) {
                            const lang = (cls || "").replace(/^language-/, "") || "text";
                            return (
                                <CodeBlock language={lang} value={text.replace(/\n$/, "")} />
                            );
                        }
                        return (
                            <code
                                className="rounded-md bg-accent/10 px-1.5 py-0.5 font-mono text-[12.5px] text-accent"
                                {...props}
                            >
                                {children}
                            </code>
                        );
                    },

                    // Pre — we render the block code ourselves in `code`, so
                    // strip the default <pre> wrapper react-markdown adds.
                    pre: ({ children }) => <>{children}</>,

                    // Blockquote — left accent rail, muted text.
                    blockquote: (props) => (
                        <blockquote
                            className="border-l-2 border-accent/40 bg-sidebar/20 py-1 pl-3 text-muted-foreground"
                            {...props}
                        />
                    ),

                    // Lists — tight bullets/numbers, comfortable nesting.
                    ul: (props) => (
                        <ul className="space-y-1 pl-5 [&_li]:list-disc [&_li::marker]:text-muted-foreground/60" {...props} />
                    ),
                    ol: (props) => (
                        <ol className="space-y-1 pl-5 [&_li]:list-decimal [&_li::marker]:text-muted-foreground/60" {...props} />
                    ),
                    li: (props) => <li className="pl-1 leading-relaxed" {...props} />,

                    // Horizontal rule — hairline.
                    hr: () => <hr className="my-4 border-0 border-t border-border/60" />,

                    // Tables — hairline borders, header emphasis.
                    table: (props) => (
                        <div className="overflow-x-auto">
                            <table
                                className="w-full border-collapse text-[13px]"
                                {...props}
                            />
                        </div>
                    ),
                    thead: (props) => <thead className="bg-sidebar/30" {...props} />,
                    th: (props) => (
                        <th
                            className="border border-border/60 px-3 py-1.5 text-left font-semibold"
                            {...props}
                        />
                    ),
                    td: (props) => (
                        <td className="border border-border/60 px-3 py-1.5 align-top" {...props} />
                    ),
                }}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
}

/**
 * CodeBlock — a fenced code block with prism highlighting + copy button.
 *
 * Reuses the same prism-react-renderer + vsDark theme as the Sandbox file
 * editor, so syntax colors stay consistent across the app. The header bar
 * shows the language and a copy affordance.
 */
function CodeBlock({ language, value }) {
    const [copied, setCopied] = useState(false);
    const { isDark } = useTheme();

    const handleCopy = async () => {
        const ok = await copyText(value);
        if (ok) {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        }
    };

    return (
        <div className="overflow-hidden rounded-lg border border-border/60 bg-card/40">
            {/* header: language label + copy button */}
            <div className="flex items-center justify-between border-b border-border/40 px-3 py-1.5">
                <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground/70">
                    {language}
                </span>
                <button
                    onClick={handleCopy}
                    className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground transition hover:bg-foreground/8 hover:text-foreground"
                    title="Copy code"
                >
                    {copied ? (
                        <>
                            <Check className="size-3 text-accent" />
                            <span className="text-accent">Copied</span>
                        </>
                    ) : (
                        <>
                            <ClipboardCopy className="size-3" />
                            Copy
                        </>
                    )}
                </button>
            </div>
            <Highlight theme={isDark ? themes.vsDark : themes.vsLight} code={value} language={language}>
                {({ className, style, tokens, getLineProps, getTokenProps }) => (
                    <pre
                        className={cn(
                            className,
                            "m-0 overflow-x-auto p-3 text-[12px] leading-relaxed"
                        )}
                        style={{ ...style, background: "transparent" }}
                    >
                        {tokens.map((line, i) => {
                            const lineProps = getLineProps({ line });
                            return (
                                <div key={i} {...lineProps}>
                                    {line.map((token, key) => (
                                        <span key={key} {...getTokenProps({ token })} />
                                    ))}
                                </div>
                            );
                        })}
                    </pre>
                )}
            </Highlight>
        </div>
    );
}
