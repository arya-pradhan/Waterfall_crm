import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { api, type Person } from "../api";
import { EmailBadge, Flags, StageSelect } from "../components/bits";
import { useApi } from "../hooks";

export function CompanyPage() {
  const id = Number(useParams().id);
  const company = useApi(() => api.company(id), [id]);
  const [note, setNote] = useState("");

  if (company.error) return <p className="error">{company.error}</p>;
  const c = company.data;
  if (!c) return null;

  const addNote = async (e: FormEvent) => {
    e.preventDefault();
    if (!note.trim()) return;
    await api.addCompanyNote(id, note.trim());
    setNote("");
    company.refresh();
  };

  return (
    <>
      <header className="profile-head">
        <h2 style={{ fontSize: "1.6rem" }}>{c.name}</h2>
        <div className="facts">
          {c.category && <span>{c.category}</span>}
          {c.rating != null && <span>{c.rating}★ from {c.review_count} reviews</span>}
          {c.phone && <a href={`tel:${c.phone}`}>{c.phone}</a>}
          {c.address && <span>{c.address}</span>}
        </div>
        <div className="row">
          {c.website && <a className="button quiet" href={c.website} target="_blank" rel="noreferrer">Open website</a>}
          {c.maps_url && <a className="button quiet" href={c.maps_url} target="_blank" rel="noreferrer">Open in Google Maps</a>}
        </div>
      </header>

      <div className="profile-grid">
        <section aria-labelledby="contacts">
          <h2 id="contacts" style={{ marginBottom: 8 }}>Contacts</h2>
          {c.people.length ? (
            c.people.map((p) => <Contact key={p.id} person={p} onChange={company.refresh} />)
          ) : (
            <p className="empty">No decision-maker found for this business. Add what you learn in the notes.</p>
          )}
        </section>

        <section aria-labelledby="notes">
          <h2 id="notes" style={{ marginBottom: 8 }}>Notes</h2>
          <form className="form" onSubmit={addNote} style={{ gap: 8 }}>
            <textarea rows={4} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you learn from their website? Anything to mention when you reach out?" aria-label="New note" />
            <div><button disabled={!note.trim()}>Add note</button></div>
          </form>
          {c.notes.map((n) => (
            <div className="note" key={n.id}>
              <div className="muted small">{new Date(n.created_at + "Z").toLocaleString()}</div>
              {n.note}
            </div>
          ))}
        </section>
      </div>
    </>
  );
}

function Contact({ person: p, onChange }: { person: Person; onChange: () => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const update = async (patch: Parameters<typeof api.updatePerson>[1]) => {
    await api.updatePerson(p.id, patch);
    onChange();
  };
  const showDraft = async () => setDraft(draft ? null : (await api.draft(p.id)).draft);
  const copy = async () => {
    await navigator.clipboard.writeText(draft ?? "");
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <article className="person">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h3>{p.name}</h3>
          {p.title && <div className="title">{p.title}</div>}
          <div style={{ marginTop: 4 }}>
            {p.email ?? <span className="muted">No email found</span>}
            <EmailBadge status={p.email_status} />
            {p.linkedin_url && <> <a href={p.linkedin_url} target="_blank" rel="noreferrer" className="small">LinkedIn</a></>}
          </div>
          <Flags reason={p.score_reason} />
        </div>
        <div className="score" title={p.score_reason ?? ""} style={{ fontSize: "1.5rem" }}>{p.score ?? "—"}</div>
      </div>
      <div className="row">
        <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          Stage <StageSelect value={p.status} label={`Stage for ${p.name}`} onChange={(status) => update({ status })} />
        </label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          Follow up
          <input type="date" value={p.follow_up_date ?? ""} onChange={(e) => update({ follow_up_date: e.target.value || null })} />
        </label>
        {p.email && <button className="quiet" onClick={showDraft}>{draft ? "Hide draft" : "Show draft"}</button>}
      </div>
      {draft && (
        <div className="form" style={{ gap: 8 }}>
          <pre className="draft">{draft}</pre>
          <div className="row">
            <button onClick={copy}>{copied ? "Copied" : "Copy draft"}</button>
            <span className="muted small">Send it from your own email, then set the stage to contacted.</span>
          </div>
        </div>
      )}
      {!!p.activity?.length && (
        <ul className="activity">
          {p.activity.slice(0, 5).map((a, i) => (
            <li key={i}>{new Date(a.created_at + "Z").toLocaleDateString()}: {a.kind.replace(":", " to ")}{a.note ? ` ${a.note}` : ""}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
