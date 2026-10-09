"""`outreach` CLI: source -> find people -> enrich -> check -> score -> draft -> track -> report."""

import csv
import datetime as dt
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import typer
from dotenv import load_dotenv

from . import db, drafting, pipeline, report
from .budget import Budget, BudgetExceeded
from .treg_client import OutOfBalance, TregClient

load_dotenv()
app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
MaxSpend = typer.Option(0.10, "--max-spend", help="Stop before this run spends more than $X.")


@contextmanager
def paid_run(max_spend: float):
    """Open DB + client + budget; turn budget/balance stops into a clean message."""
    conn, budget = db.connect(), Budget(max_spend)
    try:
        yield conn, TregClient(), budget
    except BudgetExceeded as e:
        typer.secho(f"stopped: {e}", fg="yellow")
    except OutOfBalance as e:
        body = e.body if isinstance(e.body, dict) else {}
        typer.secho(f"stopped: treg balance too low (402). top up: {body.get('topup_url', 'treg.to dashboard')}", fg="red")
    finally:
        typer.echo(f"spent this run: ${budget.spent_usd:.4f}")
        conn.close()


# ---------------------------------------------------------------- sourcing + enrichment


@app.command()
def campaign(
    query: str = typer.Argument(..., help='What you would type into Google Maps, e.g. "HVAC contractor".'),
    metro: list[str] = typer.Option(..., "--metro", "-m", help='Repeatable, e.g. -m "Abilene, TX, USA".'),
    limit: int = typer.Option(20, help="Places per metro (fetched 20 per page)."),
    max_spend: float = MaxSpend,
):
    """Integrus-style sourcing: business type x metros -> companies (via Google Maps)."""
    with paid_run(max_spend) as (conn, client, budget):
        cid = pipeline.maps_campaign(conn, client, budget, query, metro, limit, say=typer.echo)
        typer.echo(f"campaign {cid} done")


@app.command("import")
def import_(path: Path = typer.Argument(..., exists=True, help="CSV: company, domain, [person_name, title, notes]")):
    """Load a list of companies (and optionally contacts) from CSV."""
    conn = db.connect()
    pipeline.import_csv(conn, path, say=typer.echo)


@app.command("find-people")
def find_people(
    limit: int = typer.Option(50, help="Companies to process."),
    keep: int = typer.Option(2, help="Contacts to keep per company (best titles first)."),
    max_spend: float = MaxSpend,
):
    """Find decision-makers at each company (free people-search waterfall)."""
    with paid_run(max_spend) as (conn, client, budget):
        pipeline.find_people(conn, client, budget, limit=limit, keep=keep, say=typer.echo)


@app.command()
def enrich(
    limit: int = typer.Option(50, help="People to process."),
    verify: bool = typer.Option(True, help="Verify each found email (~$0.0015)."),
    benchmark: bool = typer.Option(False, help="Ask EVERY provider (head-to-head); costs ~4x."),
    max_spend: float = MaxSpend,
):
    """Find work emails through the provider waterfall, then verify them."""
    with paid_run(max_spend) as (conn, client, budget):
        pipeline.enrich_emails(conn, client, budget, limit=limit, verify=verify, benchmark=benchmark, say=typer.echo)


@app.command()
def check(n: int = typer.Option(20, help="How many unchecked hits to review.")):
    """Hand-verify a random sample of email hits. Feeds the accuracy column of the report."""
    conn = db.connect()
    rows = conn.execute("""
        SELECT a.id, a.tool_id, a.value, p.id AS pid, p.name, p.title, p.linkedin_url, p.email_status,
               p.company_location, c.name AS company, c.domain, c.address, c.website
        FROM enrichment_attempts a
        JOIN people p ON p.id = a.entity_id JOIN companies c ON c.id = p.company_id
        WHERE a.capability = 'email_find' AND a.hit = 1 AND a.cache_hit = 0
          AND a.id NOT IN (SELECT attempt_id FROM accuracy_checks)
        ORDER BY RANDOM() LIMIT ?""", (n,)).fetchall()
    if not rows:
        typer.echo("nothing to check — run `outreach enrich` first")
        return
    typer.echo("For each: is this the right person's working email? y = correct, n = wrong, s = skip, q = quit\n")
    for r in rows:
        others = conn.execute("""SELECT tool_id, value FROM enrichment_attempts
                                 WHERE capability='email_find' AND hit=1 AND entity_id=? AND id != ?""",
                              (r["pid"], r["id"])).fetchall()
        typer.secho(f"{r['value']}   ← {r['tool_id']}", bold=True)
        typer.echo(f"  person:   {r['name']} — {r['title'] or '?'}   {r['linkedin_url'] or ''}")
        typer.echo(f"  company:  {r['company']} ({r['domain']})  {r['address'] or ''}")
        if r["company_location"]:
            typer.echo(f"  provider says company is in: {r['company_location']}")
        typer.echo(f"  verifier: {r['email_status'] or 'not run'}")
        for o in others:
            typer.echo(f"  also:     {o['value']}  ({o['tool_id']})")
        ans = typer.prompt("  correct?", default="s").strip().lower()
        if ans == "q":
            break
        if ans in ("y", "n"):
            note = typer.prompt("  note (optional)", default="", show_default=False)
            conn.execute("INSERT OR REPLACE INTO accuracy_checks (attempt_id, correct, note) VALUES (?, ?, ?)",
                         (r["id"], int(ans == "y"), note or None))
            conn.commit()
        typer.echo()


# ---------------------------------------------------------------- scoring + drafting


@app.command()
def score():
    """Score every contact with a readable reason."""
    n = pipeline.score_people(db.connect())
    typer.echo(f"scored {n} contacts — see `outreach list`")


@app.command()
def draft(
    person_id: int,
    template: str = typer.Option(None, help=f"One of: {', '.join(drafting.available())}"),
):
    """Write an outreach draft (printed + saved). Never sends anything."""
    conn = db.connect()
    text = drafting.render(conn, person_id, template)
    drafting.save(conn, person_id, text)
    db.log_activity(conn, person_id, "drafted")
    typer.echo(text)


# ---------------------------------------------------------------- thin CRM

LATEST_SCORE = "(SELECT score FROM scores s WHERE s.entity_type='person' AND s.entity_id=p.id ORDER BY s.id DESC LIMIT 1)"
LATEST_REASON = "(SELECT reason FROM scores s WHERE s.entity_type='person' AND s.entity_id=p.id ORDER BY s.id DESC LIMIT 1)"


@app.command("list")
def list_(
    status: str = typer.Option(None, help=f"One of {', '.join(db.STATUSES)}"),
    limit: int = typer.Option(30),
    reasons: bool = typer.Option(False, "--reasons", help="Show score reasons."),
):
    """List contacts, best score first."""
    conn = db.connect()
    sql = f"""SELECT p.id, p.name, p.title, p.email, p.email_status, p.status, p.follow_up_date,
                     c.name AS company, {LATEST_SCORE} AS score, {LATEST_REASON} AS reason
              FROM people p JOIN companies c ON c.id = p.company_id
              {"WHERE p.status = ?" if status else ""}
              ORDER BY score DESC NULLS LAST, p.id LIMIT ?"""
    rows = conn.execute(sql, (status, limit) if status else (limit,)).fetchall()
    for r in rows:
        typer.echo(f"{r['id']:>4}  {r['score'] if r['score'] is not None else '–':>3}  {r['status']:<9} "
                   f"{r['name'][:22]:<22} {(r['title'] or '')[:24]:<24} {r['company'][:28]:<28} "
                   f"{r['email'] or '':<32} {r['email_status'] or ''}")
        if reasons and r["reason"]:
            typer.echo(f"{'':>15}{r['reason']}")


@app.command()
def mark(person_id: int, status: str):
    """Set a contact's status (new, contacted, replied, meeting, closed)."""
    if status not in db.STATUSES:
        raise typer.BadParameter(f"status must be one of {db.STATUSES}")
    conn = db.connect()
    db.update(conn, "people", person_id, status=status)
    if status == "contacted":
        conn.execute("UPDATE outreach SET status='sent_manually', sent_at=CURRENT_TIMESTAMP WHERE person_id=? AND status='drafted'", (person_id,))
    if status == "replied":
        conn.execute("UPDATE outreach SET status='replied' WHERE person_id=? AND status='sent_manually'", (person_id,))
    conn.commit()
    db.log_activity(conn, person_id, f"status:{status}")
    typer.echo(f"{person_id} -> {status}")


@app.command()
def note(person_id: int, text: str):
    """Log a note on a contact."""
    db.log_activity(db.connect(), person_id, "note", text)
    typer.echo("noted")


@app.command("follow-up")
def follow_up(person_id: int, date: str = typer.Argument(..., help="YYYY-MM-DD, or +N days")):
    """Set a follow-up date."""
    when = (dt.date.today() + dt.timedelta(days=int(date[1:]))).isoformat() if date.startswith("+") else dt.date.fromisoformat(date).isoformat()
    conn = db.connect()
    db.update(conn, "people", person_id, follow_up_date=when)
    db.log_activity(conn, person_id, "follow_up", when)
    typer.echo(f"{person_id}: follow up on {when}")


@app.command()
def due():
    """Contacts whose follow-up date is today or earlier."""
    conn = db.connect()
    rows = conn.execute("""SELECT p.id, p.name, p.status, p.follow_up_date, p.email, c.name AS company
                           FROM people p JOIN companies c ON c.id = p.company_id
                           WHERE p.follow_up_date <= date('now', 'localtime') AND p.status NOT IN ('closed')
                           ORDER BY p.follow_up_date""").fetchall()
    for r in rows:
        typer.echo(f"{r['id']:>4}  {r['follow_up_date']}  {r['status']:<9} {r['name']:<22} {r['company']:<28} {r['email'] or ''}")
    if not rows:
        typer.echo("nothing due")


@app.command()
def history(person_id: int):
    """Activity log for one contact."""
    for r in db.connect().execute("SELECT created_at, kind, note FROM activity WHERE person_id=? ORDER BY id", (person_id,)):
        typer.echo(f"{r['created_at']}  {r['kind']:<16} {r['note'] or ''}")


# ---------------------------------------------------------------- output


@app.command("report")
def report_(out: Path = typer.Option(Path("docs/report.md"), "-o", "--out")):
    """Write the waterfall report (markdown)."""
    md = report.render(db.connect())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    typer.echo(md)
    typer.secho(f"written to {out}", fg="green")


@app.command()
def export(out: Path = typer.Argument(Path("data/contacts.csv"))):
    """Export contacts to CSV (paste into Google Sheets)."""
    conn = db.connect()
    rows = conn.execute(f"""
        SELECT p.id, c.name AS company, c.domain, c.phone AS company_phone, c.address, c.category, c.rating,
               c.review_count, p.name, p.title, p.email, p.email_status, p.source_provider, p.linkedin_url,
               {LATEST_SCORE} AS score, {LATEST_REASON} AS score_reason, p.status, p.follow_up_date
        FROM people p JOIN companies c ON c.id = p.company_id ORDER BY score DESC NULLS LAST""").fetchall()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(rows[0].keys() if rows else ["id"])
        w.writerows(tuple(r) for r in rows)
    typer.echo(f"{len(rows)} contacts -> {out}")


@app.command()
def serve(port: int = typer.Option(8000, help="Port on this computer.")):
    """Build the interface, then start the app at http://127.0.0.1:PORT (only reachable from this computer)."""
    import uvicorn

    web = Path(__file__).resolve().parents[2] / "web"
    npm = shutil.which("npm")
    if not npm:
        typer.secho("Node.js is needed to build the interface. Install it from nodejs.org "
                    "(or `brew install node`), then run this again.", fg="red")
        raise typer.Exit(1)
    steps = ([[npm, "install"]] if not (web / "node_modules").is_dir() else []) + [[npm, "run", "build"]]
    for cmd in steps:
        typer.echo(f"$ {' '.join(cmd[1:])}  (in web/)")
        if subprocess.run(cmd, cwd=web).returncode:
            typer.secho("The interface didn't build; see the errors above.", fg="red")
            raise typer.Exit(1)

    typer.secho(f"Waterfall CRM is running at http://127.0.0.1:{port} — Ctrl+C to stop", fg="green")
    uvicorn.run("outreach.api:app", host="127.0.0.1", port=port)  # 127.0.0.1: not exposed to the network


@app.command()
def balance():
    """Show the treg team balance (wraps `treg balance`)."""
    exe = shutil.which("treg") or str(Path.home() / ".local/bin/treg")
    subprocess.run([exe, "balance"], check=False)


if __name__ == "__main__":
    app()
