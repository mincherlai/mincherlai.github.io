#!/usr/bin/env python3
"""Build data/publications.json (ORCID ∪ Crossref) and data/posts.json (Substack RSS). Stdlib only."""
import json, re, sys, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path

ORCID = "0000-0002-6073-0908"
FEED = "https://theautomatedlab.substack.com/feed"
API = "https://theautomatedlab.substack.com/api/v1/posts?limit=5"
MAILTO = "mincherl.jung@sjtu.edu.cn"  # Crossref polite pool
DATA = Path(__file__).resolve().parent.parent / "data"
HDR = {"Accept": "application/json", "User-Agent": f"mincherlai.github.io (mailto:{MAILTO})"}


def get(url, raw=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=60) as r:
        return r.read() if raw else json.load(r)


def orcid_works():
    for g in get(f"https://pub.orcid.org/v3.0/{ORCID}/works")["group"]:
        s = g["work-summary"][0]
        ids = {i["external-id-type"]: i["external-id-value"] for i in s["external-ids"]["external-id"]}
        if s["type"] != "journal-article" or "doi" not in ids:
            continue
        yield {
            "doi": ids["doi"].lower(),
            "title": clean_title(s["title"]["title"]["value"]),
            "journal": (s.get("journal-title") or {}).get("value", ""),
            "year": int((s.get("publication-date") or {}).get("year", {}).get("value") or 0),
        }


SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def clean_title(t):
    t = " ".join(t.split())
    t = re.sub(r"<sub>(\d+)</sub>", lambda m: m[1].translate(SUB), t)
    # Wiley's "CH 3 NH 3 PbI 3": digit after an element symbol (X or Xx) → subscript, swallow the spacer before the next symbol
    t = re.sub(r"(?:(?<=[A-Z])|(?<=\b[A-Z][a-z])) (\d)(?: (?=[A-Z][A-Za-z]{0,2} \d))?", lambda m: m[1].translate(SUB), t)
    t = re.sub(r"(?<=[A-Za-z\)])(\d{1,2})(?![\d.])", lambda m: m[1].translate(SUB), t)  # "CsPbI3", "MA3Sb2I9" (4-digit years untouched)
    return re.sub(r"<[^>]+>", "", t)


def crossref_item(m):
    ct = m.get("container-title") or [""]
    return {
        "doi": m["DOI"].lower(),
        "title": clean_title(m["title"][0]),
        "journal": ct[0],
        "year": (m.get("issued") or m.get("created"))["date-parts"][0][0],
        "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in m.get("author", [])],
    }


def crossref_works():
    url = f"https://api.crossref.org/works?filter=orcid:{ORCID}&rows=200&mailto={MAILTO}"
    return [crossref_item(m) for m in get(url)["message"]["items"] if m.get("type") == "journal-article"]


def publications():
    old = {}
    f = DATA / "publications.json"
    if f.exists():
        old = {p["doi"]: p for p in json.loads(f.read_text())}
    pubs = {}
    for p in list(orcid_works()) + crossref_works():
        cur = pubs.setdefault(p["doi"], {})
        for k, v in p.items():  # prefer non-empty values
            if v and not cur.get(k):
                cur[k] = v
    for doi, p in pubs.items():
        if not (p.get("authors") and p.get("journal")):  # ORCID summaries lack authors → one Crossref lookup, cached via old json
            o = old.get(doi, {})
            if o.get("authors") and o.get("journal"):
                p.update({k: v for k, v in o.items() if v and not p.get(k)})
            else:
                try:
                    c = crossref_item(get(f"https://api.crossref.org/works/{doi}?mailto={MAILTO}")["message"])
                    p.update({k: v for k, v in c.items() if v and not p.get(k)})
                except Exception as e:  # ponytail: a missing author list is not worth failing the run
                    print("lookup skip", doi, e, file=sys.stderr)
            p.setdefault("authors", []); p.setdefault("journal", "")
    return sorted(pubs.values(), key=lambda p: (-p["year"], p["title"]))


SCHOLAR = "https://scholar.google.com/citations?user=v7GsEJ4AAAAJ&hl=en"


def scholar_metrics():
    """Citations / h-index / i10 from the public Scholar profile (no API exists)."""
    req = urllib.request.Request(SCHOLAR, headers={"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/126.0 Safari/537.36", "Accept-Language": "en"})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
    nums = re.findall(r'<td class="gsc_rsb_std">(\d+)</td>', html)  # all, since2021, all, since2021, ...
    return {"citations": int(nums[0]), "h_index": int(nums[2]), "i10_index": int(nums[4])}


def stats(n_pubs):
    """Scholar numbers, keeping the previous ones if the scrape is blocked — the count always updates."""
    st = load("stats.json") or {}
    try:
        st.update(scholar_metrics())
        err = "ok"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        print("stats.json:", err, "— keeping previous", file=sys.stderr)
    st["publications"] = n_pubs
    return st, err


def posts():
    try:
        root = ET.fromstring(get(FEED, raw=True))
        items = [{"title": i.findtext("title"), "url": i.findtext("link"), "date": i.findtext("pubDate")}
                 for i in root.iter("item")]
    except Exception as e:  # Substack's RSS 403s from datacenter IPs; its JSON API answers there
        print("feed:", e, "— trying the JSON API", file=sys.stderr)
        items = [{"title": p["title"], "url": p["canonical_url"], "date": p["post_date"]} for p in get(API)]
    return items[:5]


def load(name):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else None


def refresh(name, fn):
    """Write data/<name> from fn(); if the source is unreachable keep the committed file.
    Upstream blocking one feed must not fail the whole run — but losing every copy does."""
    try:
        obj = fn()
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        old = load(name)
        if old is None:
            raise
        print(f"{name}: {err} — keeping previous", file=sys.stderr)
        return old, err
    write(name, obj)
    return obj, "ok"


def write(name, obj):
    p = DATA / name
    txt = json.dumps(obj, ensure_ascii=False, indent=1) + "\n"
    if p.exists() and p.read_text() == txt:
        return print(name, "unchanged")
    p.write_text(txt)
    print(name, "written", len(obj))


if __name__ == "__main__":
    assert clean_title("CH 3 NH 3 PbI 3 Cuboid") == "CH₃NH₃PbI₃ Cuboid" and clean_title("a<sub>2</sub>b <i>x</i> Phase 2 Sb 2 I 9") == "a₂b x Phase 2 Sb₂I₉" and clean_title("MA3Sb2I9 at ThinFilm2018, CsPbI3 v2.0") == "MA₃Sb₂I₉ at ThinFilm2018, CsPbI₃ v2.0"
    DATA.mkdir(exist_ok=True)
    pubs, pub_err = refresh("publications.json", publications)
    st, stat_err = stats(len(pubs))
    write("stats.json", st)
    _, post_err = refresh("posts.json", posts)
    write("_sources.json", {"publications": pub_err, "stats": stat_err, "posts": post_err})
