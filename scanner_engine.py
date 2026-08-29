import requests
from bs4 import BeautifulSoup
import re
import os
import glob
import time
from datetime import datetime
from urllib.parse import urlparse, urljoin

BUSINESS_TYPE = "restaurant"
CITY = "Milano"
AMOUNT = 50

HEADERS = {"User-Agent": "OpportunityAI-MVP/0.8 (local testing)"}
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]

MAX_INTERNAL_PAGES = 8

BOOKING_WORDS = [
    "book now", "booking", "reservation", "reserve", "reserve now",
    "prenota", "prenotazione", "prenota ora", "prenota un tavolo",
    "prenota tavolo", "reservations"
]
ORDERING_WORDS = [
    "order online", "online order", "delivery", "takeaway",
    "ordina", "ordina online", "asporto"
]
CONTACT_WORDS = [
    "contact", "contact us", "contatti", "contattaci",
    "telefono", "phone", "email", "scrivici"
]
PAGE_KEYWORDS = [
    "prenota", "booking", "reservation", "reserve",
    "contact", "contatti", "contattaci",
    "menu", "about", "chi-siamo", "chisiamo",
    "ristorante", "restaurant"
]

PARKED_TERMS = [
    "acquista questo dominio",
    "buy this domain",
    "domain for sale",
    "questo dominio è in vendita",
    "this domain is for sale",
    "dominio in vendita",
    "purchase this domain"
]

PARKING_HOSTS = [
    "sedo.com",
    "sedoparking.com",
    "afternic.com",
    "parkingcrew.net",
    "domainname.de",
    "dan.com"
]

SUSPICIOUS_TERMS = [
    "casino", "betting", "scommesse", "slot machine",
    "crypto casino", "porn", "viagra"
]


def valid_url(url):
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and "." in p.netloc
    except Exception:
        return False


def normalize_url(url):
    if not url:
        return None
    url = str(url).strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url if valid_url(url) else None


def _host(url):
    try:
        return (urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        return ""


def same_domain(a, b):
    """Strict same-site check: www/non-www are equivalent; unrelated hosts are not."""
    da = _host(a)
    db = _host(b)
    if da.startswith("www."):
        da = da[4:]
    if db.startswith("www."):
        db = db[4:]
    return bool(da and db and da == db)


def is_known_parking_host(url):
    host = _host(url)
    if host.startswith("www."):
        host = host[4:]
    return any(host == p or host.endswith("." + p) for p in PARKING_HOSTS)



TECHNICAL_EMAIL_DOMAINS = (
    "sentry-next.wixpress.com", "wixpress.com", "sentry.io",
    "example.com", "website.com"
)
TECHNICAL_EMAIL_PARTS = (
    "noreply@", "no-reply@", "donotreply@", "do-not-reply@"
)


def clean_emails(emails):
    out = []
    for raw in emails:
        email = str(raw).strip(" .,:;<>[](){}").lower()
        if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", email, re.I):
            continue
        if any(part in email for part in TECHNICAL_EMAIL_PARTS):
            continue
        domain = email.split("@", 1)[1]
        if any(domain == bad or domain.endswith("." + bad) for bad in TECHNICAL_EMAIL_DOMAINS):
            continue
        if email not in out:
            out.append(email)
    return out


def _looks_like_date_or_code(digits):
    # Dates such as 2026-08-06 / 2019-2026 and tiny fragments are not phones.
    if re.fullmatch(r"(?:19|20)\d{2}(?:19|20)\d{2}", digits):
        return True
    if digits.startswith(("19", "20")) and len(digits) <= 8:
        return True
    return False


def clean_phones(phones):
    out = []
    for raw in phones:
        value = " ".join(str(raw).split()).strip(" .,:;")
        low = value.lower()

        # Explicit dates: 07.03.2001, 07/03/2001, 2026-08-06, etc.
        if re.fullmatch(
            r"\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}",
            value
        ):
            continue
        if re.fullmatch(
            r"(?:19|20)\d{2}[./-]\d{1,2}[./-]\d{1,2}",
            value
        ):
            continue

        # Opening-hour ranges accidentally matched by the generic phone regex:
        # 14.30 19.30, 14:30-19:30, etc.
        if re.fullmatch(
            r"\d{1,2}[:.]\d{2}\s*(?:-|–|—|\s)\s*\d{1,2}[:.]\d{2}",
            value
        ):
            continue

        digits = re.sub(r"\D", "", value)

        if len(digits) < 8 or len(digits) > 13:
            continue
        if _looks_like_date_or_code(digits):
            continue
        if len(set(digits)) <= 2:
            continue

        compact = re.sub(r"[\s().\-+/]", "", value)
        if compact and not compact.isdigit():
            continue

        # For this Italy MVP, ordinary local/mobile phones generally begin
        # with 0 or 3; international forms can begin with 39/0039/+39.
        # This removes many VAT/tax/date-like numeric strings without touching
        # normal Italian numbers.
        normalized = digits
        if normalized.startswith("0039"):
            normalized = normalized[4:]
        elif value.startswith("+39") and normalized.startswith("39"):
            normalized = normalized[2:]

        if normalized and normalized[0] not in ("0", "3"):
            continue

        if value not in out:
            out.append(value)
    return out

def geocode_city(city, country_code="it"):
    print(f"Po gjej qytetin: {city}")
    r = requests.get(
        NOMINATIM_URL,
        params={
            "city": city,
            "countrycodes": country_code,
            "format": "jsonv2",
            "limit": 5,
            "addressdetails": 1,
        },
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise RuntimeError(f"Nuk u gjet qyteti '{city}'.")

    item = data[0]
    for x in data:
        if (x.get("addresstype") or "").lower() in ("city", "town", "municipality"):
            item = x
            break

    bbox = item.get("boundingbox")
    if not bbox or len(bbox) != 4:
        raise RuntimeError("Qyteti u gjet, por pa bounding box.")

    print(f"U gjet sakte: {item.get('display_name', city)}")
    return float(bbox[0]), float(bbox[2]), float(bbox[1]), float(bbox[3])


def overpass_request(query):
    errors = []
    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(1, 3):
            try:
                print(f"Po provoj Overpass: {endpoint} (tentativa {attempt}/2)")
                r = requests.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": "OpportunityAI-MVP/0.8", "Accept": "application/json"},
                    timeout=120,
                )
                if r.status_code == 200:
                    return r.json()
                errors.append(f"{endpoint} -> HTTP {r.status_code}")
            except Exception as e:
                errors.append(f"{endpoint} -> {type(e).__name__}: {e}")
            time.sleep(2)
    raise RuntimeError(" | ".join(errors[-6:]))


def load_cached_businesses(limit=50):
    """
    Build a larger persistent fallback pool by merging all previous reports,
    newest first, instead of stopping at the first 20-row cache.
    """
    files = []
    for pattern in [
        "reports/opportunity_scan_50_validation_*.csv",
        "reports/opportunity_scan_v33_*.csv",
        "reports/opportunity_scan_v32_*.csv",
        "reports/opportunity_scan_v31b_*.csv",
        "reports/opportunity_scan_v31_*.csv",
        "reports/opportunity_scan_v3_*.csv",
        "reports/opportunity_scan_v2c_*.csv",
    ]:
        files.extend(glob.glob(pattern))

    files = sorted(set(files), key=os.path.getmtime, reverse=True)

    out, seen = [], set()

    for f in files:
        try:
            df = pd.read_csv(f)
            if "business_name" not in df.columns or "website" not in df.columns:
                continue

            for _, row in df.iterrows():
                website = normalize_url(row.get("website", ""))
                if not website:
                    continue

                key = website.lower().rstrip("/")
                if key in seen:
                    continue

                seen.add(key)
                out.append({
                    "name": str(row.get("business_name", "Unknown")).strip() or "Unknown",
                    "website": website,
                    "phone_osm": "",
                    "email_osm": "",
                    "instagram_osm": "",
                })

                if len(out) >= limit:
                    print(f"\nU ndertua CACHE i bashkuar me {len(out)} biznese nga raportet e meparshme.")
                    return out
        except Exception:
            pass

    if out:
        print(f"\nU ndertua CACHE i bashkuar me {len(out)} biznese nga raportet e meparshme.")
    return out


def find_businesses(city, business_type, limit=20):
    south, west, north, east = geocode_city(city, "it")
    amenity = "restaurant"

    query = f"""
    [out:json][timeout:90];
    (
      nwr["amenity"="{amenity}"]["website"]({south},{west},{north},{east});
      nwr["amenity"="{amenity}"]["contact:website"]({south},{west},{north},{east});
    );
    out tags center;
    """

    try:
        data = overpass_request(query)
    except Exception as e:
        print("\nOverpass perkohesisht deshtoi:")
        print(str(e))
        cached = load_cached_businesses(limit)
        if cached:
            return cached
        raise

    out, seen = [], set()

    for element in data.get("elements", []):
        tags = element.get("tags", {})
        website = normalize_url(tags.get("website") or tags.get("contact:website"))
        if not website:
            continue
        key = website.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "name": tags.get("name", "Unknown"),
            "website": website,
            "phone_osm": tags.get("phone") or tags.get("contact:phone") or "",
            "email_osm": tags.get("email") or tags.get("contact:email") or "",
            "instagram_osm": tags.get("contact:instagram") or tags.get("instagram") or "",
        })

        if len(out) >= limit:
            break

    return out


def text_contains(text, words):
    low = text.lower()
    return [w for w in words if w in low]


def get_visible_and_structural_text(soup, html):
    chunks = [soup.get_text(" ", strip=True)]

    for tag in soup.find_all(["a", "button", "input"]):
        chunks.append(tag.get_text(" ", strip=True))
        for attr in ("href", "value", "aria-label", "title", "onclick"):
            val = tag.get(attr)
            if val:
                chunks.append(str(val))

    return " ".join(chunks) + " " + html


def collect_internal_pages(base_url, soup):
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        label = a.get_text(" ", strip=True)
        if not href:
            continue

        absolute = urljoin(base_url, href)
        if not same_domain(base_url, absolute):
            continue

        hay = (absolute + " " + label).lower()
        score = 999
        for i, key in enumerate(PAGE_KEYWORDS):
            if key in hay:
                score = i
                break

        if score < 999:
            candidates.append((score, absolute))

    candidates.sort(key=lambda x: x[0])

    unique = []
    for _, u in candidates:
        clean = u.split("#")[0].rstrip("/")
        if clean not in unique:
            unique.append(clean)
        if len(unique) >= MAX_INTERNAL_PAGES - 1:
            break
    return unique


def detect_parked_domain(final_url, soup, visible_text):
    """
    HIGH confidence only:
    1) visible sale/parking language, OR
    2) actual final redirect host is a known parking marketplace.
    Merely seeing 'sedo' / 'afternic' inside JS/HTML is NOT enough.
    """
    evidence = []
    visible_low = visible_text.lower()

    phrases = [p for p in PARKED_TERMS if p in visible_low]
    if phrases:
        evidence.append("visible text: " + ", ".join(phrases[:2]))

    try:
        host = urlparse(final_url).netloc.lower().replace("www.", "")
    except Exception:
        host = ""

    parking_redirect = any(
        host == ph or host.endswith("." + ph)
        for ph in PARKING_HOSTS
    )

    if parking_redirect:
        evidence.append("redirected to parking host: " + host)

    # Also accept an explicit sale link only when its visible anchor text
    # itself says the domain is for sale/buyable.
    explicit_sale_link = False
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True).lower()
        href = a.get("href", "").lower()
        if any(p in label for p in PARKED_TERMS):
            explicit_sale_link = True
            evidence.append("explicit sale link: " + label[:100])
            break

    parked = bool(phrases or parking_redirect or explicit_sale_link)
    return parked, evidence


def inspect_page(url, html):
    soup = BeautifulSoup(html, "html.parser")
    visible = soup.get_text(" ", strip=True)
    structural = get_visible_and_structural_text(soup, html)

    emails = re.findall(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        html
    )
    phones = re.findall(r"(\+?\d[\d\s().-]{7,}\d)", visible)

    booking_hits = text_contains(structural, BOOKING_WORDS)
    ordering_hits = text_contains(structural, ORDERING_WORDS)
    contact_hits = text_contains(structural, CONTACT_WORDS)
    parked, parked_evidence = detect_parked_domain(url, soup, visible)
    suspicious_hits = text_contains(structural, SUSPICIOUS_TERMS)

    emails = clean_emails(emails)
    phones = clean_phones(phones)

    return {
        "soup": soup,
        "visible": visible,
        "booking_hits": booking_hits,
        "ordering_hits": ordering_hits,
        "contact_hits": contact_hits,
        "emails": emails[:5],
        "phones": phones[:5],
        "instagram": "instagram.com" in html.lower(),
        "facebook": "facebook.com" in html.lower(),
        "parked": parked,
        "parked_evidence": parked_evidence,
        "suspicious_hits": suspicious_hits,
        "url": url,
    }


def add_evidence(evidence, category, detail, url):
    evidence.append(f"{category}: {detail} @ {url}")


def analyze_website(business):
    result = {
        "business_name": business["name"],
        "website": business["website"],
        "status": "UNKNOWN",
        "reachable": False,
        "title": "",
        "pages_checked": 0,
        "booking_found": False,
        "ordering_found": False,
        "contact_found": False,
        "email_found": False,
        "phone_found": False,
        "social_found": False,
        "parked_domain": False,
        "suspicious_content": False,
        "opportunity_score": None,
        "confidence": "LOW",
        "primary_problem": "",
        "recommended_action": "",
        "evidence": [],
        "signals": [],
    }

    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }

    try:
        home = requests.get(
            business["website"],
            headers=browser_headers,
            timeout=15,
            allow_redirects=True,
        )

        if home.status_code in (401, 403, 429):
            result["status"] = "BLOCKED"
            result["signals"] = [f"Website blocked scanner (HTTP {home.status_code})"]
            return result

        if home.status_code >= 400:
            result["status"] = "UNREACHABLE"
            result["signals"] = [f"HTTP error {home.status_code}"]
            return result

        original_website = business["website"]
        homepage_external_redirect = not same_domain(original_website, home.url)

        # Foreign redirects are NOT business evidence. The only exception is a
        # known domain-parking host, because that is itself a strong opportunity.
        if homepage_external_redirect and not is_known_parking_host(home.url):
            result["status"] = "UNRELATED_REDIRECT"
            result["reachable"] = False
            result["signals"] = [
                f"Website redirects to unrelated domain: {_host(home.url)}"
            ]
            result["primary_problem"] = "Website redirects to an unrelated domain"
            result["recommended_action"] = "Verify business website manually before outreach"
            result["confidence"] = "LOW"
            return result

        result["reachable"] = True
        pages = [(home.url, home.text)]

        home_inspect = inspect_page(home.url, home.text)
        soup = home_inspect["soup"]

        if soup.title and soup.title.string:
            result["title"] = soup.title.string.strip()

        internal_candidates = (
            collect_internal_pages(home.url, soup)
            if not homepage_external_redirect
            else []
        )
        for internal in internal_candidates:
            try:
                r = requests.get(internal, headers=browser_headers, timeout=12, allow_redirects=True)
                if r.status_code < 400:
                    if same_domain(home.url, r.url):
                        pages.append((r.url, r.text))
                    else:
                        print("    External redirect ignored:", internal, "->", r.url)
                time.sleep(0.15)
            except Exception:
                pass

        evidence = []
        all_visible = []

        for page_url, html in pages:
            p = inspect_page(page_url, html)
            all_visible.append(p["visible"])

            if p["booking_hits"]:
                result["booking_found"] = True
                add_evidence(evidence, "BOOKING", ", ".join(p["booking_hits"][:3]), page_url)

            if p["ordering_hits"]:
                result["ordering_found"] = True
                add_evidence(evidence, "ORDERING", ", ".join(p["ordering_hits"][:3]), page_url)

            if p["contact_hits"]:
                result["contact_found"] = True
                add_evidence(evidence, "CONTACT", ", ".join(p["contact_hits"][:3]), page_url)

            if p["emails"]:
                result["email_found"] = True
                add_evidence(evidence, "EMAIL", p["emails"][0], page_url)

            if p["phones"]:
                result["phone_found"] = True
                add_evidence(evidence, "PHONE", p["phones"][0], page_url)

            if p["instagram"] or p["facebook"]:
                result["social_found"] = True
                add_evidence(evidence, "SOCIAL", "social link found", page_url)

            if p["parked"]:
                result["parked_domain"] = True
                for parked_ev in p["parked_evidence"][:2]:
                    add_evidence(evidence, "PARKED", parked_ev, page_url)

            if p["suspicious_hits"]:
                result["suspicious_content"] = True
                add_evidence(evidence, "SUSPICIOUS", ", ".join(p["suspicious_hits"][:3]), page_url)

        result["pages_checked"] = len(pages)

        osm_emails = clean_emails([business["email_osm"]]) if business["email_osm"] else []
        if osm_emails:
            result["email_found"] = True
            add_evidence(evidence, "EMAIL", osm_emails[0], "OSM")

        osm_phones = clean_phones([business["phone_osm"]]) if business["phone_osm"] else []
        if osm_phones:
            result["phone_found"] = True
            add_evidence(evidence, "PHONE", osm_phones[0], "OSM")

        if business["instagram_osm"]:
            result["social_found"] = True
            add_evidence(evidence, "SOCIAL", business["instagram_osm"], "OSM")

        score = 0
        signals = []

        # Strong, verified problems first
        if result["parked_domain"]:
            score += 70
            signals.append("Domain appears parked/for sale")

        if result["suspicious_content"]:
            score += 35
            signals.append("Suspicious or unrelated website content")

        if not home.url.startswith("https://"):
            score += 15
            signals.append("No HTTPS")

        # Missing features only count after several pages were checked
        enough_pages = result["pages_checked"] >= 3

        if enough_pages and not result["booking_found"]:
            score += 15
            signals.append("No booking found after deep check")

        if enough_pages and not result["contact_found"]:
            score += 10
            signals.append("No contact CTA found after deep check")

        if enough_pages and not result["email_found"]:
            score += 5
            signals.append("No public email found after deep check")

        if enough_pages and not result["phone_found"]:
            score += 5
            signals.append("No public phone found after deep check")

        # Ordering is weak signal: very small weight
        if enough_pages and not result["ordering_found"]:
            score += 3
            signals.append("No online ordering found")

        if result["social_found"] and score >= 15:
            score += 7
            signals.append("Active social presence + website weakness")

        score = min(score, 100)
        result["opportunity_score"] = score

        if result["parked_domain"]:
            result["primary_problem"] = "Website/domain appears abandoned or parked"
            result["recommended_action"] = "Offer a complete website replacement"
            result["confidence"] = "HIGH"

        elif result["suspicious_content"]:
            result["primary_problem"] = "Website content appears unrelated/suspicious"
            result["recommended_action"] = "Offer urgent website cleanup/rebuild"
            result["confidence"] = "HIGH"

        elif score >= 40:
            result["primary_problem"] = "Several verified website weaknesses"
            result["recommended_action"] = "Offer website conversion/booking improvements"
            result["confidence"] = "MEDIUM"

        elif score >= 20:
            result["primary_problem"] = "Some website weaknesses detected"
            result["recommended_action"] = "Review manually before outreach"
            result["confidence"] = "MEDIUM"

        else:
            result["primary_problem"] = "No strong opportunity detected"
            result["recommended_action"] = "Do not prioritize"
            result["confidence"] = "LOW"

        if score >= 70:
            result["status"] = "STRONG_OPPORTUNITY"
        elif score >= 40:
            result["status"] = "POSSIBLE_OPPORTUNITY"
        else:
            result["status"] = "GOOD_SITE"

        result["evidence"] = evidence
        result["signals"] = signals
        return result

    except requests.exceptions.Timeout:
        result["status"] = "UNREACHABLE"
        result["signals"] = ["Website timeout"]
        return result
    except requests.exceptions.ConnectionError:
        result["status"] = "UNREACHABLE"
        result["signals"] = ["Connection error"]
        return result
    except Exception as e:
        result["status"] = "ERROR"
        result["signals"] = [type(e).__name__]
        return result


def main():
    print()
    print("==========================================")
    print(" OpportunityAI Scanner V3.6 - MVP Accuracy Lock")
    print("==========================================")
    print()
    print(f"Automatic test: {AMOUNT} {BUSINESS_TYPE}s in {CITY}")
    print()

    businesses = find_businesses(CITY, BUSINESS_TYPE, AMOUNT)

    print()
    print(f"Po analizohen {len(businesses)} biznese...")
    print()

    results = []

    for i, business in enumerate(businesses, start=1):
        print(f"[{i}/{len(businesses)}] {business['name']}")
        print(f"    {business['website']}")

        r = analyze_website(business)
        results.append(r)

        score_text = "N/A" if r["opportunity_score"] is None else f'{r["opportunity_score"]}/100'

        print(f"    STATUS: {r['status']}")
        print(f"    SCORE: {score_text}")
        print(f"    CONFIDENCE: {r['confidence']}")
        print(f"    PAGES CHECKED: {r['pages_checked']}")

        if r["primary_problem"]:
            print(f"    PROBLEM: {r['primary_problem']}")
        if r["recommended_action"]:
            print(f"    ACTION: {r['recommended_action']}")
        if r["signals"]:
            print("    SIGNALS: " + " | ".join(r["signals"]))
        if r["evidence"]:
            print("    EVIDENCE:")
            for ev in r["evidence"][:5]:
                print(f"      - {ev}")

        print()
        time.sleep(0.35)

    import pandas as pd  # local import: only needed when exporting CLI reports
    df = pd.DataFrame(results)

    df["_sort"] = pd.to_numeric(df["opportunity_score"], errors="coerce").fillna(-1)
    df = df.sort_values("_sort", ascending=False).drop(columns=["_sort"])

    os.makedirs("reports", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"reports/opportunity_scan_v36_mvp_{ts}.csv"
    df.to_csv(filename, index=False, encoding="utf-8-sig")

    print()
    print("==========================================")
    print("          TOP OPPORTUNITIES")
    print("==========================================")
    print()

    valid = df[df["opportunity_score"].notna()].head(10)

    for _, row in valid.iterrows():
        print(f"{int(row['opportunity_score'])}/100 | {row['status']} | {row['confidence']}")
        print(f"    {row['business_name']}")
        print(f"    {row['website']}")
        print(f"    PROBLEM: {row['primary_problem']}")
        print(f"    ACTION: {row['recommended_action']}")
        print(f"    Pages checked: {row['pages_checked']}")
        if row["signals"]:
            print(f"    SIGNALS: {' | '.join(row['signals'])}")
        if row["evidence"]:
            print("    EVIDENCE:")
            for ev in row["evidence"][:4]:
                print(f"      - {ev}")
        print()

    print(f"Raporti: {filename}")


if __name__ == "__main__":
    main()
