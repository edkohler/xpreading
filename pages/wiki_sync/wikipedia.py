"""Small MediaWiki API client plus wikitext clean-up.

We read raw wikitext (not rendered HTML) because it keeps table structure
(rowspans, headings) that the extractor needs, and the revisions API lets us
skip pages that have not changed since the last run.
"""

import os
import re
import time
from urllib.parse import unquote, urlparse

import requests

API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = os.getenv(
    "WIKI_SYNC_USER_AGENT",
    "xpreading-award-sync/1.0 (https://xpreading.com; award list updater)",
)

# Sections that never hold award lists but can be long.
DROP_SECTIONS = re.compile(
    r"^==\s*(See also|References|Notes|Footnotes|Citations|Sources|"
    r"External links|Further reading|Bibliography)\s*==\s*$",
    re.I | re.M,
)


def title_from_url(url):
    """'https://en.wikipedia.org/wiki/Golden_Duck_Award#Hal_Clement_Award' -> 'Golden_Duck_Award'."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    if "wikipedia.org" not in parsed.netloc or not parsed.path.startswith("/wiki/"):
        return None
    title = unquote(parsed.path[len("/wiki/") :])
    return title.replace(" ", "_") or None


def section_from_url(url):
    frag = urlparse(url.strip()).fragment
    return unquote(frag).replace("_", " ") if frag else ""


def _session():
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _get(session, params, retries=3):
    params = {**params, "format": "json", "formatversion": "2"}
    for attempt in range(retries):
        try:
            r = session.get(API_URL, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def latest_revisions(titles):
    """Return {requested_title: {"revid", "timestamp", "resolved_title", "missing"}}.

    One request per 50 titles; does not download page content.
    """
    session = _session()
    out = {}
    titles = list(titles)
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        data = _get(
            session,
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "ids|timestamp",
                "redirects": 1,
                "titles": "|".join(t.replace("_", " ") for t in batch),
            },
        )
        q = data.get("query", {})
        # Map requested -> normalized -> redirect target
        alias = {}
        for n in q.get("normalized", []):
            alias[n["from"]] = n["to"]
        for rd in q.get("redirects", []):
            alias[rd["from"]] = rd["to"]

        def resolve(name):
            seen = set()
            while name in alias and name not in seen:
                seen.add(name)
                name = alias[name]
            return name

        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in batch:
            p = pages.get(resolve(t.replace("_", " ")), {})
            rev = (p.get("revisions") or [{}])[0]
            out[t] = {
                "revid": rev.get("revid"),
                "timestamp": rev.get("timestamp"),
                "resolved_title": p.get("title"),
                "missing": bool(p.get("missing")) or not rev,
            }
    return out


def fetch_wikitext(title):
    """Return (revid, wikitext) for the latest revision of a page."""
    data = _get(
        _session(),
        {
            "action": "query",
            "prop": "revisions",
            "rvprop": "ids|content",
            "rvslots": "main",
            "redirects": 1,
            "titles": title.replace("_", " "),
        },
    )
    page = data["query"]["pages"][0]
    if page.get("missing"):
        raise LookupError(f"Wikipedia page not found: {title}")
    rev = page["revisions"][0]
    return rev["revid"], rev["slots"]["main"]["content"]


def _strip_templates(text, names):
    """Remove {{name ...}} templates (with nesting) for the given lowercase names."""
    out, i, n = [], 0, len(text)
    pattern = re.compile(r"\{\{\s*(" + "|".join(names) + r")\b", re.I)
    while i < n:
        m = pattern.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i : m.start()])
        depth, j = 0, m.start()
        while j < n:
            if text.startswith("{{", j):
                depth += 1
                j += 2
            elif text.startswith("}}", j):
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        i = j
    return "".join(out)


def clean_wikitext(text):
    """Shrink wikitext for the extractor without losing list/table structure."""
    # Cut trailing reference-type sections (keep everything before the first one).
    m = DROP_SECTIONS.search(text)
    if m:
        text = text[: m.start()]
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<ref[^>/]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = _strip_templates(
        text,
        [
            "cite",
            "citation",
            "efn",
            "refn",
            "sfn",
            "reflist",
            "notelist",
            "infobox",
            "portal",
            "short description",
            "use [a-z]+ dates",
            "dead link",
            "citation needed",
            "anchor",
            "webarchive",
            "commons",
        ],
    )
    text = re.sub(
        r"\[\[(?:File|Image|Category):[^\]]*(?:\[\[[^\]]*\]\][^\]]*)*\]\]",
        "",
        text,
        flags=re.I,
    )
    # [[Target|Label]] -> Label ; [[Target]] -> Target
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r'style="[^"]*"\s*\|?', "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
