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
    text = text.replace("\x00", "")
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


_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)


def _norm_anchor(text):
    text = unquote(text or "")
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)  # [[a|b]] -> b
    text = re.sub(r"'{2,}", "", text)
    return re.sub(r"[\s_]+", " ", text).strip().lower()


def split_sections(text):
    """[(level, anchor, start, end)] for each == heading ==; anchors follow
    Wikipedia's rule of suffixing repeated headings with _2, _3, ..."""
    heads = [(len(m.group(1)), m.group(2), m.start()) for m in _HEADING.finditer(text)]
    out, counts = [], {}
    for i, (level, title, start) in enumerate(heads):
        end = len(text)
        for level2, _, start2 in heads[i + 1 :]:
            if level2 <= level:
                end = start2
                break
        base = _norm_anchor(title)
        counts[base] = counts.get(base, 0) + 1
        anchor = base if counts[base] == 1 else f"{base} {counts[base]}"
        out.append((level, anchor, start, end))
    return out


def slice_sections(text, anchors):
    """Return only the linked sections (plus their parent headings for
    context), or the full text if any anchor is missing or not found."""
    anchors = [_norm_anchor(a) for a in anchors]
    if not anchors or not all(anchors):
        return text
    sections = split_sections(text)
    by_anchor = {a: (lvl, s, e) for lvl, a, s, e in sections}
    if not all(a in by_anchor for a in anchors):
        return text
    parts = []
    first = sections[0][2] if sections else len(text)
    parts.append(text[: min(first, 1500)])  # page intro, for context
    for a in anchors:
        level, start, end = by_anchor[a]
        parents = [
            text[s : text.index("\n", s) if "\n" in text[s:] else len(text)]
            for lvl, _, s, e in sections
            if lvl < level and s < start < e
        ]
        parts.append("\n".join(parents + [text[start:end].rstrip()]))
    return "\n\n".join(parts)
