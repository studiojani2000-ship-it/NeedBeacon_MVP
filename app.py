from flask import Flask, render_template, request, redirect, url_for, Response, abort
import csv, os, re
from datetime import datetime, timezone
from pathlib import Path

app = Flask(__name__)
PUBLIC_BASE_URL = "https://needbeacon.onrender.com"
WAITLIST_FILE = Path(os.getenv("WAITLIST_FILE", "data/waitlist.csv"))
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$")


def _ensure_store():
    WAITLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not WAITLIST_FILE.exists():
        with WAITLIST_FILE.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["created_utc", "email", "service", "role", "willingness"])


def _already_joined(email):
    _ensure_store()
    with WAITLIST_FILE.open("r", newline="", encoding="utf-8") as f:
        return any((row.get("email") or "").lower() == email.lower() for row in csv.DictReader(f))


@app.get("/")
def index():
    return render_template("index.html", joined=request.args.get("joined") == "1")


@app.post("/join")
def join():
    email = request.form.get("email", "").strip().lower()[:160]
    service = request.form.get("service", "").strip()[:120]
    role = request.form.get("role", "").strip()[:80]
    willingness = request.form.get("willingness", "").strip()[:80]
    if not EMAIL_RE.match(email):
        return redirect(url_for("index") + "#early-access")
    _ensure_store()
    if not _already_joined(email):
        with WAITLIST_FILE.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([datetime.now(timezone.utc).isoformat(), email, service, role, willingness])
    return redirect(url_for("index", joined=1) + "#early-access")


@app.get("/admin/waitlist")
def admin_waitlist():
    secret = os.getenv("WAITLIST_ADMIN_KEY", "")
    if not secret or request.args.get("key") != secret:
        abort(404)
    _ensure_store()
    with WAITLIST_FILE.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    html = ["<!doctype html><meta name='robots' content='noindex'><link rel='stylesheet' href='/static/style.css'><div class='admin-wrap'>",
            f"<h1>NeedBeacon early-access requests: {len(rows)}</h1>",
            "<table><tr><th>Date UTC</th><th>Email</th><th>Service</th><th>Role</th><th>Payment signal</th></tr>"]
    import html as h
    for r in reversed(rows):
        html.append("<tr>" + "".join(f"<td>{h.escape(r.get(k,'') or '')}</td>" for k in ["created_utc","email","service","role","willingness"]) + "</tr>")
    html.append("</table><p style='color:#94a3b8'>Note: Render Free storage is ephemeral; export/record meaningful signups before redeploys or restarts.</p></div>")
    return "".join(html)


@app.get("/robots.txt")
def robots():
    return Response(f"User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: {PUBLIC_BASE_URL}/sitemap.xml\n", mimetype="text/plain")


@app.get("/sitemap.xml")
def sitemap():
    body = f'''<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{PUBLIC_BASE_URL}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url></urlset>'''
    return Response(body, mimetype="application/xml")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
