import { useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { api, STAGES, type Person, type Stage } from "../api";
import { EmailBadge, StageSelect, When } from "../components/bits";
import { useApi } from "../hooks";

const STAGE_TEXT: Record<Stage, string> = {
  new: "New",
  contacted: "Contacted",
  replied: "Replied",
  meeting: "Meeting",
  closed: "Closed",
};

export function Crm() {
  const people = useApi(api.people);
  const [over, setOver] = useState<Stage | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);

  // Move locally first so the card lands immediately; the server call follows.
  const move = async (id: number, status: Stage) => {
    people.setData((people.data ?? []).map((p) => (p.id === id ? { ...p, status } : p)));
    try {
      await api.updatePerson(id, { status });
    } catch {
      people.refresh();
    }
  };

  const onDrop = (stage: Stage) => (e: DragEvent) => {
    e.preventDefault();
    setOver(null);
    const id = Number(e.dataTransfer.getData("text/plain"));
    if (id) move(id, stage);
  };

  if (people.error) return <p className="error">{people.error}</p>;
  if (!people.data) return <p className="muted">Loading contacts…</p>;
  const all = people.data;
  if (!all.length) {
    return <p className="empty">Contacts from your searches land in New. <Link to="/search">Run a search</Link> to fill the board.</p>;
  }

  return (
    <>
      <p className="muted">Drag a contact to change its stage, or use the menu on the card.</p>
      <div className="board">
        {STAGES.map((stage) => {
          const cards = all.filter((p) => p.status === stage);
          return (
            <section
              key={stage}
              className={`column${over === stage ? " over" : ""}`}
              aria-label={STAGE_TEXT[stage]}
              onDragOver={(e) => { e.preventDefault(); setOver(stage); }}
              onDragLeave={() => setOver((s) => (s === stage ? null : s))}
              onDrop={onDrop(stage)}
            >
              <h2>{STAGE_TEXT[stage]} <span className="muted">{cards.length}</span></h2>
              {cards.map((p) => <Card key={p.id} person={p} dragging={dragging === p.id} setDragging={setDragging} onMove={move} />)}
            </section>
          );
        })}
      </div>
    </>
  );
}

function Card({ person: p, dragging, setDragging, onMove }: {
  person: Person;
  dragging: boolean;
  setDragging: (id: number | null) => void;
  onMove: (id: number, s: Stage) => void;
}) {
  return (
    <article
      className={`card${dragging ? " dragging" : ""}`}
      draggable
      onDragStart={(e) => { e.dataTransfer.setData("text/plain", String(p.id)); setDragging(p.id); }}
      onDragEnd={() => setDragging(null)}
    >
      <Link to={`/companies/${p.company_id}`}>{p.name}</Link>
      <span className="title">{p.company}</span>
      {p.email && <span className="small">{p.email}<EmailBadge status={p.email_status} /></span>}
      {p.follow_up_date && <span className="small">Follow up <When date={p.follow_up_date} /></span>}
      <StageSelect value={p.status} label={`Stage for ${p.name}`} onChange={(s) => onMove(p.id, s)} />
    </article>
  );
}
