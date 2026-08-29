from flask import Flask, render_template, request, redirect, url_for, Response, abort
import os, re, html as h
from datetime import datetime, timezone
import requests

app = Flask(__name__)
PUBLIC_BASE_URL = "https://needbeacon.onrender.com"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$")


def _supabase_config():
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL or SUPABASE_SECRET_KEY is missing")
    return url, key


def _headers(prefer=None):
    _, key = _supabase_config()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _waitlist_endpoint():
    url, _ = _supabase_config()
    return f"{url}/rest/v1/waitlist"


def _already_joined(email):
    r = requests.get(
        _waitlist_endpoint(),
        headers=_headers(),
        params={"select": "id", "email": f"eq.{email}", "limit": "1"},
        timeout=15,
    )
    r.raise_for_status()
    return bool(r.json())


def _insert_waitlist(email, service, role, willingness):
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "email": email,
        "service": service,
        "role": role,
        "payment_signal": willingness,
    }
    r = requests.post(
        _waitlist_endpoint(),
        headers=_headers("return=minimal"),
        json=payload,
        timeout=15,
    )
    r.raise_for_status()


def _get_waitlist():
    r = requests.get(
        _waitlist_endpoint(),
        headers=_headers(),
        params={"select": "created_at,email,service,role,payment_signal", "order": "created_at.desc"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


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
    try:
        if not _already_joined(email):
            _insert_waitlist(email, service, role, willingness)
    except requests.RequestException:
        app.logger.exception("Supabase waitlist write failed")
        return Response("Early-access signup is temporarily unavailable. Please try again shortly.", status=503)
    return redirect(url_for("index", joined=1) + "#early-access")


@app.get("/admin/waitlist")
def admin_waitlist():
    secret = os.getenv("WAITLIST_ADMIN_KEY", "")
    if not secret or request.args.get("key") != secret:
        abort(404)
    try:
        rows = _get_waitlist()
    except requests.RequestException:
        app.logger.exception("Supabase waitlist read failed")
        return Response("Could not load waitlist from Supabase.", status=503)

    out = ["<!doctype html><meta name='robots' content='noindex'><link rel='stylesheet' href='/static/style.css'><div class='admin-wrap'>",
           f"<h1>NeedBeacon early-access requests: {len(rows)}</h1>",
           "<table><tr><th>Date UTC</th><th>Email</th><th>Service</th><th>Role</th><th>Payment signal</th></tr>"]
    for r in rows:
        vals = [r.get("created_at", ""), r.get("email", ""), r.get("service", ""), r.get("role", ""), r.get("payment_signal", "")]
        out.append("<tr>" + "".join(f"<td>{h.escape(str(v or ''))}</td>" for v in vals) + "</tr>")
    out.append("</table><p style='color:#94a3b8'>Stored persistently in Supabase.</p></div>")
    return "".join(out)


@app.get("/robots.txt")
def robots():
    return Response(f"User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: {PUBLIC_BASE_URL}/sitemap.xml\n", mimetype="text/plain")


@app.get("/sitemap.xml")
def sitemap():
    body = f'''<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{PUBLIC_BASE_URL}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url></urlset>'''
    return Response(body, mimetype="application/xml")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
