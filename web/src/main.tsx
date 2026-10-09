import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { useApi, usd } from "./hooks";
import { Home } from "./pages/Home";
import { Search } from "./pages/Search";
import { Outreach } from "./pages/Outreach";
import { CompanyPage } from "./pages/Company";
import { Crm } from "./pages/Crm";
import "./styles.css";

const TITLES: Record<string, string> = { "/": "Home", "/search": "Search", "/outreach": "Outreach", "/crm": "CRM" };

function Balance() {
  const { data, error } = useApi(api.balance, [], 60_000);
  if (error || data?.error) return <span className="balance err" title={data?.error ?? error ?? ""}>treg balance unavailable</span>;
  return (
    <span className={`balance${data?.low ? " low" : ""}`} title="Remaining treg credit. Searches stop before going over their cap.">
      <span className="muted">treg balance</span> <strong>{usd(data?.balance_usd)}</strong>
    </span>
  );
}

function Shell() {
  const { pathname } = useLocation();
  const title = TITLES[pathname] ?? (pathname.startsWith("/companies") ? "Company" : "");
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <rect x="1" y="2" width="16" height="3" rx="1" fill="var(--fall-1)" />
            <rect x="4" y="7.5" width="12" height="3" rx="1" fill="var(--fall-3)" />
            <rect x="7" y="13" width="8" height="3" rx="1" fill="var(--fall-5)" />
          </svg>
          Waterfall
        </div>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>Home</NavLink>
          <NavLink to="/search">Search</NavLink>
          <NavLink to="/outreach">Outreach</NavLink>
          <NavLink to="/crm">CRM</NavLink>
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <h1>{title}</h1>
          <Balance />
        </header>
        <main className="page">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/search" element={<Search />} />
            <Route path="/outreach" element={<Outreach />} />
            <Route path="/companies/:id" element={<CompanyPage />} />
            <Route path="/crm" element={<Crm />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </StrictMode>,
);
