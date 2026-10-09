import { STAGES, type Stage } from "../api";
import { relativeDays } from "../hooks";

/** Verifier verdict next to an email. "valid" only means the mailbox exists. */
export function EmailBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const kind = status === "valid" ? "valid" : status === "invalid" ? "invalid" : status.includes("risky") ? "risky" : "unknown";
  const label = status === "valid-risky" ? "catch-all" : status;
  const help: Record<string, string> = {
    valid: "Mailbox exists. It doesn't prove the address belongs to this person.",
    risky: "The domain accepts any address, so this one can't be confirmed.",
    invalid: "This mailbox doesn't exist. Don't send.",
    unknown: "The verifier couldn't tell.",
  };
  return <span className={`badge ${kind}`} title={help[kind]}>{label}</span>;
}

export function StageSelect({ value, onChange, label }: { value: Stage; onChange: (s: Stage) => void; label: string }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value as Stage)}>
      {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
    </select>
  );
}

export function When({ date, days }: { date: string; days?: number }) {
  const d = days ?? Math.round((new Date(date).getTime() - new Date(new Date().toDateString()).getTime()) / 86400000);
  return <span className={`when${d < 0 ? " overdue" : d <= 2 ? " soon" : ""}`}>{relativeDays(d)}</span>;
}

/** Flags the scorer raised, pulled out of the score reason so they're visible in tables. */
export function Flags({ reason }: { reason: string | null }) {
  if (!reason) return null;
  const flags = reason.split("; ").filter((r) => r.startsWith("WRONG-COMPANY") || r.includes("≠"));
  if (!flags.length) return null;
  return (
    <div className="flag">
      {flags.map((f) => <div key={f}>{f.startsWith("WRONG-COMPANY") ? "Possible wrong company: " + f.split(": ")[1] : f}</div>)}
    </div>
  );
}
