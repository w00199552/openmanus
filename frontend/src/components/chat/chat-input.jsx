import { useEffect, useRef, useState } from "react";
import {
    Send,
    Plus,
    Paperclip,
    Cpu,
    Square,
    AtSign,
    Sparkles,
    Check,
} from "lucide-react";

import { cn } from "@/lib/utils";
import {
    Tooltip,
    TooltipTrigger,
    TooltipContent,
} from "@/components/ui/tooltip";
import { listSkills } from "@/services/agent-service";

const BACKEND = (import.meta.env && import.meta.env.VITE_BACKEND_URL) || "";

/**
 * ChatInput — ZCode-style input bar with /skill command support.
 *
 * When the user types "/skill", a dropdown appears listing available skills
 * from ~/.openmanus/skills/. Selecting one fills the input with "/skill <name>".
 */
export function ChatInput({
    onSend,
    onStop,
    onNewChat,
    isLoading,
    showNewChat = false,
}) {
    const [value, setValue] = useState("");
    const taRef = useRef(null);
    const [skills, setSkills] = useState([]);
    const [showSkillPicker, setShowSkillPicker] = useState(false);
    const [skillIndex, setSkillIndex] = useState(0);

    // load skills on mount
    useEffect(() => {
        listSkills()
            .then(setSkills)
            .catch(() => {});
    }, []);

    // auto-grow
    useEffect(() => {
        const ta = taRef.current;
        if (!ta) return;
        ta.style.height = "auto";
        ta.style.height = `${ta.scrollHeight}px`;
    }, [value]);

    // detect /skill command in input
    useEffect(() => {
        const trimmed = value.trim();
        if (trimmed === "/skill" || trimmed === "/skill ") {
            setShowSkillPicker(true);
            setSkillIndex(0);
        } else {
            setShowSkillPicker(false);
        }
    }, [value]);

    const submit = () => {
        const text = value.trim();
        if (!text || isLoading) return;
        setShowSkillPicker(false);
        onSend(text);
        setValue("");
    };

    const selectSkill = (name) => {
        setValue(`/skill ${name} `);
        setShowSkillPicker(false);
        taRef.current?.focus();
    };

    const onKeyDown = (e) => {
        // skill picker navigation
        if (showSkillPicker && skills.length > 0) {
            if (e.key === "ArrowDown") {
                e.preventDefault();
                setSkillIndex((i) => Math.min(i + 1, skills.length - 1));
                return;
            }
            if (e.key === "ArrowUp") {
                e.preventDefault();
                setSkillIndex((i) => Math.max(i - 1, 0));
                return;
            }
            if (e.key === "Enter" || e.key === "Tab") {
                e.preventDefault();
                selectSkill(skills[skillIndex].name);
                return;
            }
            if (e.key === "Escape") {
                e.preventDefault();
                setShowSkillPicker(false);
                return;
            }
        }
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
        }
    };

    return (
        <div className="relative px-2 pb-3 pt-2">
            <div className="content-narrow">
                {/* skill picker dropdown */}
                {showSkillPicker && skills.length > 0 && (
                    <div className="absolute bottom-full left-2 right-2 mb-1 max-h-60 overflow-y-auto rounded-lg border border-border/60 bg-popover shadow-lg">
                        <div className="px-3 py-2 text-[11px] font-medium text-muted-foreground/60">
                            <Sparkles className="mr-1 inline size-3" /> Select a
                            skill
                        </div>
                        {skills.map((skill, i) => (
                            <button
                                key={skill.name}
                                onClick={() => selectSkill(skill.name)}
                                onMouseEnter={() => setSkillIndex(i)}
                                className={cn(
                                    "flex w-full items-center gap-2 px-3 py-2 text-left transition",
                                    i === skillIndex
                                        ? "bg-accent/10"
                                        : "hover:bg-sidebar/40"
                                )}
                            >
                                <Sparkles
                                    className={cn(
                                        "size-3.5 shrink-0",
                                        i === skillIndex
                                            ? "text-accent"
                                            : "text-muted-foreground/50"
                                    )}
                                />
                                <div className="min-w-0 flex-1">
                                    <div className="text-[13px] font-medium">
                                        {skill.name}
                                    </div>
                                    <div className="truncate text-[11px] text-muted-foreground/60">
                                        {skill.description}
                                    </div>
                                </div>
                                {i === skillIndex && (
                                    <Check className="size-3 shrink-0 text-accent" />
                                )}
                            </button>
                        ))}
                    </div>
                )}

                <div className="rounded-2xl border border-border/60 bg-card px-2.5 py-2 transition focus-within:border-accent/40 focus-within:shadow-[0_0_0_3px_hsl(var(--accent)/0.12)]">
                    {/* textarea */}
                    <textarea
                        ref={taRef}
                        value={value}
                        onChange={(e) => setValue(e.target.value)}
                        onKeyDown={onKeyDown}
                        rows={1}
                        placeholder="Message manus…  (/skill, /cd, Shift+Enter for newline)"
                        className="block max-h-52 min-h-[2.75rem] w-full resize-none bg-transparent px-1 text-[14px] leading-relaxed outline-none placeholder:text-muted-foreground/50"
                    />

                    {/* toolbar row */}
                    <div className="mt-1.5 flex items-center gap-1">
                        {showNewChat && (
                            <ToolBtn
                                label="New conversation"
                                onClick={onNewChat}
                            >
                                <Plus className="size-4" />
                            </ToolBtn>
                        )}
                        <ToolBtn label="Attach (coming soon)">
                            <Paperclip className="size-4" />
                        </ToolBtn>
                        <ToolBtn label="Model (coming soon)">
                            <Cpu className="size-4" />
                        </ToolBtn>
                        <ToolBtn
                            label="Skills"
                            onClick={() => {
                                setValue("/skill ");
                                taRef.current?.focus();
                            }}
                        >
                            <Sparkles className="size-4" />
                        </ToolBtn>
                        <ToolBtn label="Mention / delegate (coming soon)">
                            <AtSign className="size-4" />
                        </ToolBtn>

                        <div className="flex-1" />

                        {isLoading ? (
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <button
                                        onClick={onStop}
                                        className="flex size-7 items-center justify-center rounded-full bg-destructive/15 text-destructive transition hover:bg-destructive/25"
                                    >
                                        <Square className="size-3.5" />
                                    </button>
                                </TooltipTrigger>
                                <TooltipContent side="top">Stop</TooltipContent>
                            </Tooltip>
                        ) : (
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <button
                                        onClick={submit}
                                        disabled={!value.trim()}
                                        className={cn(
                                            "flex size-7 items-center justify-center rounded-full transition",
                                            value.trim()
                                                ? "bg-accent text-accent-foreground accent-glow hover:bg-accent/90"
                                                : "bg-muted/30 text-muted-foreground/40"
                                        )}
                                    >
                                        <Send className="size-3.5" />
                                    </button>
                                </TooltipTrigger>
                                <TooltipContent side="top">Send</TooltipContent>
                            </Tooltip>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

function ToolBtn({ children, label, onClick }) {
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <button
                    type="button"
                    onClick={onClick}
                    className="rounded-md p-1.5 text-muted-foreground transition hover:bg-sidebar/60 hover:text-foreground"
                >
                    {children}
                </button>
            </TooltipTrigger>
            <TooltipContent side="top">{label}</TooltipContent>
        </Tooltip>
    );
}
