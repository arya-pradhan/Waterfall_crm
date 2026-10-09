// Typed wrappers for the Python API (src/outreach/api.py). Every screen talks to the server through here.

export const STAGES = ["new", "contacted", "replied", "meeting", "closed"] as const;
export type Stage = (typeof STAGES)[number];

export type Progress = {
  companies: number;
  with_domain: number;
  people_searched: number;
  contacts: number;
  enriched: number;
  emails: number;
  verified: number;
};

export type Job = {
  id: number;
  campaign_id: number | null;
  query: string;
  locations: string[];
  per_location: number;
  status: "queued" | "running" | "paused" | "done" | "failed";
  stage: "maps" | "people" | "emails" | "scoring" | "done" | null;
  message: string | null;
  spent_usd: number;
  max_spend_usd: number;
  created_at: string;
  updated_at: string;
  progress: Progress | null;
};

export type Estimate = {
  companies: number;
  contacts: number;
  cost_usd: number;
  minutes: number;
  suggested_cap_usd: number;
  basis: string;
  note: string;
};

export type Group = {
  id: number;
  kind: "maps" | "list";
  query: string;
  locations: string[];
  created_at: string;
  companies: number;
  contacts: number;
  emails: number;
  job_status: Job["status"] | null;
  job_id: number | null;
  progress: Progress;
};

export type ContactRow = {
  company_id: number;
  company: string;
  domain: string | null;
  website: string | null;
  phone: string | null;
  location: string | null;
  category: string | null;
  rating: number | null;
  review_count: number | null;
  person_id: number | null;
  name: string | null;
  title: string | null;
  email: string | null;
  email_status: string | null;
  linkedin_url: string | null;
  status: Stage | null;
  follow_up_date: string | null;
  score: number | null;
  score_reason: string | null;
};

export type Person = {
  id: number;
  company_id: number;
  company: string;
  name: string;
  title: string | null;
  email: string | null;
  email_status: string | null;
  linkedin_url: string | null;
  status: Stage;
  follow_up_date: string | null;
  score: number | null;
  score_reason: string | null;
  days_until?: number;
  activity?: { kind: string; note: string | null; created_at: string }[];
};

export type Company = {
  id: number;
  name: string;
  domain: string | null;
  website: string | null;
  phone: string | null;
  address: string | null;
  location: string | null;
  category: string | null;
  rating: number | null;
  review_count: number | null;
  maps_url: string | null;
  people: Person[];
  notes: { id: number; note: string; created_at: string }[];
  groups: { id: number; query: string }[];
};

export type Balance = { balance_usd: number | null; error: string | null; low: boolean };

export type SearchInput = { query: string; locations: string[]; per_location: number; max_spend?: number };

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().then((d) => d.detail, () => res.statusText);
    throw new Error(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  balance: () => request<Balance>("GET", "/balance"),
  estimate: (s: SearchInput) => request<Estimate>("POST", "/estimate", s),
  startSearch: (s: SearchInput) => request<Job>("POST", "/searches", s),
  jobs: () => request<Job[]>("GET", "/jobs"),
  resumeJob: (id: number, max_spend?: number) => request<Job>("POST", `/jobs/${id}/resume`, { max_spend }),
  groups: () => request<Group[]>("GET", "/groups"),
  groupContacts: (id: number) => request<ContactRow[]>("GET", `/groups/${id}/contacts`),
  company: (id: number) => request<Company>("GET", `/companies/${id}`),
  addCompanyNote: (id: number, text: string) => request("POST", `/companies/${id}/notes`, { text }),
  people: () => request<Person[]>("GET", "/people"),
  upcoming: () => request<Person[]>("GET", "/upcoming"),
  updatePerson: (id: number, patch: { status?: Stage; follow_up_date?: string | null }) =>
    request<Person>("PATCH", `/people/${id}`, patch),
  draft: (id: number) => request<{ draft: string }>("GET", `/people/${id}/draft`),
};
