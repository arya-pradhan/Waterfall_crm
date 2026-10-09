import type { Job, Progress } from "../api";

// The current search drawn as the pipeline it is: each stage steps down and narrows as counts fall.
const STEPS = [
  { key: "companies", label: "businesses found", stage: "maps", color: "var(--fall-1)" },
  { key: "with_domain", label: "have their own website", stage: "maps", color: "var(--fall-2)" },
  { key: "contacts", label: "decision-makers found", stage: "people", color: "var(--fall-3)" },
  { key: "emails", label: "emails found", stage: "emails", color: "var(--fall-4)" },
  { key: "verified", label: "emails verified", stage: "emails", color: "var(--fall-5)" },
] as const;

const ORDER = ["maps", "people", "emails", "scoring", "done"];

type Props = { progress: Progress | null; stage: Job["stage"]; running: boolean };

export function Waterfall({ progress: p, stage, running }: Props) {
  const top = Math.max(p?.companies ?? 0, 1);
  const reached = ORDER.indexOf(stage ?? "maps");

  return (
    <ol className="fall" aria-label="Search progress by stage">
      {STEPS.map((s, i) => {
        const count = p?.[s.key] ?? 0;
        const stageIndex = ORDER.indexOf(s.stage);
        const pending = stageIndex > reached;
        const active = running && stageIndex === reached;
        return (
          <li key={s.key} className={active ? "active" : undefined} style={{ ["--step" as string]: i }}>
            <div
              className={`bar${pending ? " pending" : ""}`}
              style={{ ["--r" as string]: pending ? 0.25 : count / top, ["--c" as string]: s.color }}
            />
            <div className="label">
              <span className="count">{pending ? "—" : count}</span>
              <span className="muted">{s.label}</span>
              {active && <span className="small">{subProgress(p, s.stage)}</span>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function subProgress(p: Progress | null, stage: string): string {
  if (!p) return "";
  if (stage === "people") return `searching ${p.people_searched} of ${p.with_domain}`;
  if (stage === "emails") return `checked ${p.enriched} of ${p.contacts}`;
  return "searching Maps";
}
