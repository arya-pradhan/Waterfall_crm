import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { api, type Estimate, type Job } from "../api";
import { useApi, usd } from "../hooks";

export function Search() {
  const [query, setQuery] = useState("");
  const [cityDraft, setCityDraft] = useState("");
  const [cities, setCities] = useState<string[]>([]);
  const [perCity, setPerCity] = useState(20);
  const [cap, setCap] = useState("");
  const [capTouched, setCapTouched] = useState(false);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const jobs = useApi(api.jobs, [], 3000);

  // Re-estimate shortly after the inputs settle; prefill the cap until the user edits it.
  useEffect(() => {
    if (query.trim().length < 2 || !cities.length) return setEstimate(null);
    const t = setTimeout(async () => {
      try {
        const e = await api.estimate({ query, locations: cities, per_location: perCity });
        setEstimate(e);
        if (!capTouched) setCap(e.suggested_cap_usd.toFixed(2));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }, 400);
    return () => clearTimeout(t);
  }, [query, cities, perCity, capTouched]);

  const addCity = () => {
    const c = cityDraft.trim();
    if (c && !cities.includes(c)) setCities([...cities, c]);
    setCityDraft("");
  };
  const onCityKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {  // not ",": "Austin, TX" needs the comma
      e.preventDefault();
      addCity();
    }
  };

  const start = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setStarting(true);
    try {
      await api.startSearch({ query: query.trim(), locations: cities, per_location: perCity, max_spend: Number(cap) || undefined });
      setQuery("");
      setCities([]);
      setCapTouched(false);
      jobs.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  const ready = query.trim().length >= 2 && cities.length > 0 && Number(cap) > 0;

  return (
    <>
      <div className="search-grid">
        <form className="form" onSubmit={start}>
          <label>
            Business type
            <span className="hint">What you'd type into Google Maps</span>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="HVAC contractor" required />
          </label>
          <label>
            Cities
            <span className="hint">Press Enter after each one. City and state work best.</span>
            <input value={cityDraft} onChange={(e) => setCityDraft(e.target.value)} onKeyDown={onCityKey} onBlur={addCity} placeholder="Austin, TX" />
          </label>
          {cities.length > 0 && (
            <div className="chips">
              {cities.map((c) => (
                <span className="chip" key={c}>
                  {c}
                  <button type="button" aria-label={`Remove ${c}`} onClick={() => setCities(cities.filter((x) => x !== c))}>×</button>
                </span>
              ))}
            </div>
          )}
          <div className="row">
            <label>
              Businesses per city
              <input type="number" min={1} max={500} value={perCity} onChange={(e) => setPerCity(Math.max(1, Math.min(500, Number(e.target.value) || 1)))} />
            </label>
            <label>
              Spending cap (USD)
              <input type="number" min={0.01} step={0.01} value={cap} onChange={(e) => { setCap(e.target.value); setCapTouched(true); }} />
            </label>
          </div>
          {error && <p className="error">{error}</p>}
          <div><button disabled={!ready || starting}>{starting ? "Starting…" : "Start search"}</button></div>
        </form>

        <aside className="estimate" aria-live="polite">
          {estimate ? (
            <>
              <span className="muted">Estimated cost</span>
              <span className="big">{usd(estimate.cost_usd)}</span>
              <dl>
                <dt>Time</dt><dd>about {estimate.minutes < 1 ? "1 minute" : `${Math.round(estimate.minutes)} minutes`}</dd>
                <dt>Businesses</dt><dd>up to {estimate.companies}</dd>
                <dt>Contacts</dt><dd>about {estimate.contacts}</dd>
              </dl>
              <p className="muted small">Based on {estimate.basis}. The search pauses before it would spend past your cap.</p>
            </>
          ) : (
            <p className="muted">Add a business type and a city to see what the search will cost.</p>
          )}
        </aside>
      </div>

      <section aria-labelledby="searches">
        <div className="section-head"><h2 id="searches">Searches</h2></div>
        {jobs.data?.length ? (
          <ul className="list jobs">
            {jobs.data.map((j) => <JobRow key={j.id} job={j} />)}
          </ul>
        ) : (
          <p className="empty">Searches started here run in the background, even if you close this tab.</p>
        )}
      </section>
    </>
  );
}

function JobRow({ job }: { job: Job }) {
  const p = job.progress;
  const pct =
    job.status === "done" ? 100
    : !p ? 0
    : job.stage === "maps" ? 10
    : job.stage === "people" ? 10 + 40 * (p.people_searched / Math.max(p.with_domain, 1))
    : job.stage === "emails" ? 50 + 50 * (p.enriched / Math.max(p.contacts, 1))
    : 98;
  return (
    <li>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span>
          <strong>{job.query}</strong> <span className="muted">in {job.locations.join("; ")}</span>
        </span>
        <span className="muted small">{usd(job.spent_usd)} of {usd(job.max_spend_usd)}</span>
      </div>
      <div className="meter" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="row small muted" style={{ justifyContent: "space-between" }}>
        <span>{job.status}{job.message ? `: ${job.message}` : ""}</span>
        {job.campaign_id && <Link to={`/outreach?group=${job.campaign_id}`}>View results</Link>}
      </div>
    </li>
  );
}
