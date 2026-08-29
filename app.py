from flask import Flask, render_template, request, redirect, url_for
from scanner_engine import find_businesses, analyze_website
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import re

app = Flask(__name__)
LAST_RESULT = None

DISCOVERY_POOL = 50
DEFAULT_SHOW = 10
MAX_WORKERS = 6

def build_outreach(result, city):
    name = result.get("business_name") or result.get("name") or "your restaurant"
    problem = result.get("problem") or "a website issue"
    signals = result.get("signals") or []
    evidence = result.get("evidence") or []

    email = ""
    phone = ""
    for item in evidence:
        text = str(item)
        if not email and "EMAIL:" in text:
            m = re.search(r'EMAIL:\s*([^\s@]+@[^\s@]+)', text, re.I)
            if m:
                email = m.group(1).rstrip(".,;")
        if not phone and "PHONE:" in text:
            phone = text.split("PHONE:", 1)[1].split("@", 1)[0].strip()

    strongest = signals[0] if signals else problem
    subject = f"Quick website idea for {name}"
    message = (
        f"Hi {name} team,\n\n"
        f"I came across your restaurant while researching businesses in {city}. "
        f"I noticed a specific website issue: {strongest.lower().rstrip('.')}. "
        f"I design and improve websites for businesses, and I think this is something that could be fixed "
        f"to make it easier for customers to find and contact you.\n\n"
        f"If useful, I can send you a short no-obligation suggestion for what I would change.\n\n"
        f"Best regards"
    )
    return {
        "email": email,
        "phone": phone,
        "subject": subject,
        "message": message,
    }


def sort_results(results):
    def key(item):
        score = item.get("opportunity_score")
        return -1 if score is None else score
    return sorted(results, key=key, reverse=True)

def analyze_many(businesses):
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(analyze_website, b): b for b in businesses}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                pass
    return results

@app.route("/", methods=["GET", "POST"])
def index():
    global LAST_RESULT

    context = {
        "results": None,
        "error": None,
        "city": "Milano",
        "show_count": DEFAULT_SHOW,
        "elapsed": None,
        "analyzed_count": 0,
        "pool_count": 0,
    }

    if request.method == "GET":
        if LAST_RESULT:
            context.update(LAST_RESULT)
        return render_template("index.html", **context)

    city = request.form.get("city", "").strip()
    try:
        show_count = int(request.form.get("show_count", str(DEFAULT_SHOW)))
    except ValueError:
        show_count = DEFAULT_SHOW

    show_count = max(5, min(show_count, 20))
    context.update(city=city, show_count=show_count)

    if not city:
        context["error"] = "Write a city."
        LAST_RESULT = context
        return redirect(url_for("index"))

    started = time.time()

    try:
        businesses = find_businesses(city, "restaurant", DISCOVERY_POOL)
    except Exception as exc:
        context["error"] = f"Business discovery failed: {exc}"
        LAST_RESULT = context
        return redirect(url_for("index"))

    context["pool_count"] = len(businesses)

    results = analyze_many(businesses)
    ranked = sort_results(results)

    for result in ranked:
        score = result.get("opportunity_score")
        confidence = str(result.get("confidence") or "").upper()
        if score is not None and score >= 20 and confidence in {"MEDIUM", "HIGH"}:
            result["outreach"] = build_outreach(result, city)
        else:
            result["outreach"] = None

    context["results"] = ranked[:show_count]
    context["analyzed_count"] = len(results)
    context["elapsed"] = round(time.time() - started, 1)

    LAST_RESULT = context
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
