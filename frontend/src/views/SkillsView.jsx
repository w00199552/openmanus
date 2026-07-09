import {observer} from "mobx-react-lite";
import {useEffect, useState} from "react";
import {Sparkles, FileText, Code, BookOpen, ChevronLeft} from "lucide-react";

import {useStore} from "@/hooks/useStore";
import {Avatar} from "@/components/Avatar";
import {cn} from "@/lib/utils";

/**
 * SkillsView — card grid of skills from ~/.openmanus/skills/.
 * Click a card to see SKILL.md content (via API detail endpoint later;
 * for now shows metadata only).
 */
export const SkillsView = observer(function SkillsView() {
  const {skillStore} = useStore();
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    skillStore.loadSkills();
  }, [skillStore]);

  if (skillStore.loading) {
    return <Centered>Loading skills…</Centered>;
  }

  if (selected) {
    const skill = skillStore.skills.find((s) => s.name === selected);
    if (skill) {
      return <SkillDetail skill={skill} onBack={() => setSelected(null)}/>;
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="mb-6 flex items-center gap-2">
          <Sparkles className="size-5 text-accent"/>
          <h1 className="text-lg font-semibold">Skills</h1>
          <span className="text-sm text-muted-foreground">
            ({skillStore.skills.length})
          </span>
        </div>

        {skillStore.skills.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border/40 p-12 text-center">
            <Sparkles className="mx-auto mb-3 size-8 text-muted-foreground/30"/>
            <p className="text-sm text-muted-foreground">
              No skills installed yet.
            </p>
            <p className="mt-1 text-[12px] text-muted-foreground/60">
              Copy skill directories to ~/.openmanus/skills/
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {skillStore.skills.map((skill) => (
              <SkillCard key={skill.name} skill={skill} onClick={() => setSelected(skill.name)}/>
            ))}
          </div>
        )}
      </div>
    </div>
  );
});

function SkillCard({skill, onClick}) {
  return (
    <button
      onClick={onClick}
      className="group rounded-xl border border-border/60 bg-card p-4 text-left transition hover:border-accent/40 hover:bg-sidebar/30"
    >
      <div className="mb-3 flex items-center gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent/10">
          <Sparkles className="size-5 text-accent"/>
        </div>
        <div className="min-w-0">
          <span className="truncate text-sm font-medium">{skill.name}</span>
          <div className="mt-0.5 flex gap-1">
            {skill.has_scripts && (
              <span className="rounded-sm bg-accent/10 px-1.5 py-0.5 text-[9px] text-accent">
                scripts
              </span>
            )}
            {skill.has_references && (
              <span className="rounded-sm bg-muted/20 px-1.5 py-0.5 text-[9px] text-muted-foreground">
                refs
              </span>
            )}
          </div>
        </div>
      </div>
      <p className="line-clamp-2 text-[11px] text-muted-foreground/70">
        {skill.description || "(no description)"}
      </p>
    </button>
  );
}

function SkillDetail({skill, onBack}) {
  return (
    <div className="flex h-full">
      <div className="flex w-56 shrink-0 flex-col border-r border-border/60 bg-sidebar/20">
        <button
          onClick={onBack}
          className="flex items-center gap-1 px-4 py-3 text-sm text-muted-foreground transition hover:text-foreground"
        >
          <ChevronLeft className="size-4"/>
          Skills
        </button>
        <div className="px-4 py-2">
          <div className="flex items-center gap-2">
            <div className="flex size-9 items-center justify-center rounded-lg bg-accent/10">
              <Sparkles className="size-4.5 text-accent"/>
            </div>
            <div>
              <div className="text-sm font-medium">{skill.name}</div>
            </div>
          </div>
        </div>
        <div className="mt-2 flex flex-col gap-0.5 px-2">
          <div className="flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-accent">
            <FileText className="size-3.5"/>
            Overview
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-6 px-6 py-6">
          <div>
            <h2 className="mb-2 text-sm font-medium">Description</h2>
            <p className="text-[13px] leading-relaxed text-muted-foreground/80">
              {skill.description || "(no description)"}
            </p>
          </div>

          <div>
            <h2 className="mb-2 text-sm font-medium">Capabilities</h2>
            <div className="flex gap-2">
              <Capability icon={<FileText className="size-3"/>} label="SKILL.md" active/>
              <Capability icon={<Code className="size-3"/>} label="Scripts" active={skill.has_scripts}/>
              <Capability icon={<BookOpen className="size-3"/>} label="References" active={skill.has_references}/>
            </div>
          </div>

          <div>
            <h2 className="mb-2 text-sm font-medium">SKILL.md Content</h2>
            <div className="rounded-lg border border-border/40 bg-sidebar/20 px-4 py-3 text-[12px] text-muted-foreground/50">
              SKILL.md preview requires API endpoint (GET /skills/:name). Coming soon.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Capability({icon, label, active}) {
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[11px]",
        active ? "border-accent/30 bg-accent/5 text-accent" : "border-border/30 text-muted-foreground/40",
      )}
    >
      {icon}
      {label}
    </div>
  );
}

function Centered({children}) {
  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-sm text-muted-foreground">{children}</p>
    </div>
  );
}
