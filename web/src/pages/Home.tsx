import { Link } from "react-router-dom";
import { api, type Group, type Job } from "../api";
import { Waterfall } from "../components/Waterfall";
import { When } from "../components/bits";
import { useApi, usd } from "../hooks";

/** The search to feature: one that's running or waiting, else the most recent. */
function featured(jobs: Job[]): Job | undefined {
  return jobs.find((j) => j.status === "running" || j.status === "queued") ?? jobs.find((j) => j.status === "paused") ?? jobs[0];
}

export function Home() {
  const jobs = useApi(api.jobs, [], 3000);
  const groups = useApi(api.groups, [], 10_000);
  const upcoming = useApi(api.upcoming, [], 30_000);
  const job = jobs.data ? featured(jobs.data) : undefined;
  // Groups made from the CLI have no job; show the newest one so the page is never blank.
  const group = !job && groups.data?.length ? groups.data[0] : undefined;

  return (
    <>
      <section className="fall-panel" aria-labelledby="current">
        {job ? <CurrentSearch job={job} onResume={jobs.refresh} /> : group ? <LatestGroup group={group} /> : <FirstRun />}
      </section>

      <div className="split">
        <section aria-labelledby="up-next">
          <div className="section-head">
            <h2 id="up-next">Up next</h2>
            <Link to="/crm" className="small">Open CRM</Link>
          </div>
          {upcoming.data?.length ? (
            <ul className="list">
              {upcoming.data.map((p) => (
                <li key={p.id}>
                  <span>
                    <Link to={`/companies/${p.company_id}`}>{p.name}</Link>
                    <span className="muted small"> at {p.company}, {p.status}</span>
                  </span>
                  <When date={p.follow_up_date!} days={p.days_until} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">No follow-ups scheduled. Set a follow-up date on a contact and it shows up here.</p>
          )}
        </section>

        <section aria-labelledby="groups">
          <div className="section-head">
            <h2 id="groups">Groups</h2>
            <Link to="/search" className="small">New search</Link>
          </div>
          {groups.data?.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Search</th><th className="num">Businesses</th><th className="num">Contacts</th><th className="num">Emails</th></tr>
                </thead>
                <tbody>
                  {groups.data.map((g) => (
                    <tr key={g.id}>
                      <td>
                        <Link to={`/outreach?group=${g.id}`}>{g.query}</Link>
                        <div className="title">{g.locations.join("; ")}</div>
                      </td>
                      <td className="num">{g.companies}</td>
                      <td className="num">{g.contacts}</td>
                      <td className="num">{g.emails}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">Searches you run are saved here as groups.</p>
          )}
        </section>
      </div>
    </>
  );
}

const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "Waiting to start",
  running: "Running",
  paused: "Paused",
  done: "Finished",
  failed: "Stopped with an error",
};

function CurrentSearch({ job, onResume }: { job: Job; onResume: () => void }) {
  const resume = async () => {
    const cap = window.prompt("Spending cap for the rest of this search (USD)", String(Math.max(job.max_spend_usd * 1.5, job.spent_usd + 0.25).toFixed(2)));
    if (cap === null) return;
    await api.resumeJob(job.id, Number(cap));
    onResume();
  };
  return (
    <>
      <div className="fall-head">
        <div>
          <h2 id="current">{job.query} in {job.locations.join("; ")}</h2>
          <p className="muted">
            {STATUS_TEXT[job.status]}{job.message && job.status !== "done" ? `: ${job.message}` : ""}
          </p>
        </div>
        <div className="row">
          <span className="muted small">{usd(job.spent_usd)} of {usd(job.max_spend_usd)} cap</span>
          {(job.status === "paused" || job.status === "failed") && <button onClick={resume}>Resume search</button>}
          {job.campaign_id && job.status === "done" && <Link className="button quiet" to={`/outreach?group=${job.campaign_id}`}>Open in Outreach</Link>}
        </div>
      </div>
      <Waterfall progress={job.progress} stage={job.stage} running={job.status === "running"} />
    </>
  );
}

function LatestGroup({ group }: { group: Group }) {
  return (
    <>
      <div className="fall-head">
        <div>
          <h2 id="current">{group.query} in {group.locations.join("; ")}</h2>
          <p className="muted">Latest group</p>
        </div>
        <Link className="button quiet" to={`/outreach?group=${group.id}`}>Open in Outreach</Link>
      </div>
      <Waterfall progress={group.progress} stage="done" running={false} />
    </>
  );
}

function FirstRun() {
  return (
    <div className="fall-head">
      <div>
        <h2 id="current">No searches yet</h2>
        <p className="muted">Pick a business type and a city. You'll see the cost before anything runs.</p>
      </div>
      <Link className="button" to="/search">Start a search</Link>
    </div>
  );
}
