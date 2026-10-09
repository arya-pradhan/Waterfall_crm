import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type ContactRow, type Stage } from "../api";
import { EmailBadge, Flags, StageSelect } from "../components/bits";
import { useApi } from "../hooks";

export function Outreach() {
  const [params, setParams] = useSearchParams();
  const groups = useApi(api.groups);
  const groupId = Number(params.get("group")) || groups.data?.[0]?.id;
  const rows = useApi(() => (groupId ? api.groupContacts(groupId) : Promise.resolve([] as ContactRow[])), [groupId]);
  const [withEmail, setWithEmail] = useState(false);

  const setStage = async (row: ContactRow, status: Stage) => {
    await api.updatePerson(row.person_id!, { status });
    rows.setData((rows.data ?? []).map((r) => (r.person_id === row.person_id ? { ...r, status } : r)));
  };

  if (groups.data && !groups.data.length) {
    return <p className="empty">No groups yet. <Link to="/search">Run a search</Link> and its businesses show up here.</p>;
  }
  const shown = (rows.data ?? []).filter((r) => !withEmail || r.email);
  const group = groups.data?.find((g) => g.id === groupId);

  return (
    <section aria-label="Outreach table">
      <div className="row" style={{ marginBottom: 16, justifyContent: "space-between" }}>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          Group
          <select value={groupId ?? ""} onChange={(e) => setParams({ group: e.target.value })}>
            {groups.data?.map((g) => (
              <option key={g.id} value={g.id}>{g.query} in {g.locations.join("; ")}</option>
            ))}
          </select>
        </label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 8, fontWeight: 400 }}>
          <input type="checkbox" checked={withEmail} onChange={(e) => setWithEmail(e.target.checked)} />
          Only contacts with an email
        </label>
      </div>
      {group && <p className="muted small" style={{ marginBottom: 12 }}>{group.companies} businesses, {group.contacts} contacts, {group.emails} emails. Best fit first; hover a score for the reasons.</p>}
      {rows.error && <p className="error">{rows.error}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Business</th>
              <th>Contact</th>
              <th>Email</th>
              <th className="num">Score</th>
              <th>Stage</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={`${r.company_id}-${r.person_id ?? "none"}`} className={r.person_id ? undefined : "no-contact"}>
                <td>
                  <Link to={`/companies/${r.company_id}`}>{r.company}</Link>
                  <div className="title">
                    {r.rating != null && `${r.rating}★ (${r.review_count} reviews)`}
                    {r.domain ? ` ${r.domain}` : " no website"}
                  </div>
                </td>
                <td>
                  {r.name ?? "No contact found"}
                  {r.title && <div className="title">{r.title}</div>}
                </td>
                <td>
                  {r.email ?? <span className="muted">—</span>}
                  <EmailBadge status={r.email_status} />
                  <Flags reason={r.score_reason} />
                </td>
                <td className="num score" title={r.score_reason ?? ""}>{r.score ?? "—"}</td>
                <td>{r.person_id && r.status && <StageSelect value={r.status} label={`Stage for ${r.name}`} onChange={(s) => setStage(r, s)} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
