"""Turn a cleaned Wikipedia page into structured award entries with an LLM.

Every page formats its lists differently (tables with rowspans, bullet lists,
per-year headings, prose), so instead of 58 hand-written parsers we give the
model the page plus examples of how *our* database already records that
category (year convention, award level names, sub-category split) and ask
for strictly-typed JSON. Everything downstream (matching, writing) is
deterministic Python.
"""

import json
import os
import time

import requests

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = os.getenv("WIKI_SYNC_MODEL", "gpt-5-mini")
# Reading rows out of a table needs little reasoning; low effort is much faster.
REASONING_EFFORT = os.getenv("WIKI_SYNC_REASONING_EFFORT", "low")
TIMEOUT = int(os.getenv("WIKI_SYNC_TIMEOUT", "900"))

SYSTEM_PROMPT = """You extract children's/YA book award data from Wikipedia wikitext for a reading-list website.

Rules:
- Each category has an "Extract" line. "years >= N" means return only that category's entries from year N onward. "ALL years" means the category is new to our database: return its complete history, every year the page lists.
- Only return entries for the categories listed under "Categories to extract". Entries belonging to the "Other categories on this page" are handled separately: skip them.
- Return every book listed for those years: winners AND non-winners (honor books, nominees, finalists, shortlists, runners-up, ranked places, selections). We track them all.
- Assign each entry to exactly one of the given categories (by category_id). Several categories can share one page (age groups, divisions, author vs illustrator awards, fiction vs nonfiction). Use the category names, notes, and existing examples to decide. If an entry fits none of the categories, skip it.
- Use the SAME year convention as the existing examples for that category (usually the award year shown on the page).
- award_level must be one of the allowed level names, chosen to match how the existing examples for that category use levels; use null only if nothing fits. Put the page's own wording (e.g. "Honor", "Finalist", "2nd place") in level_text.
- Titles: the book title only, without italics markup, footnotes, publisher, or translator. Keep subtitles if the page shows them.
- Authors/illustrators: split into first_name and last_name ("Kate DiCamillo" -> Kate / DiCamillo; "{{Sortname|María Dolores|Águila}}" -> María Dolores / Águila). Single-name creators: put the name in both fields. Do not list translators. "X and Y" means two people. For illustrator awards, the illustrator is still listed under illustrators and the author under authors when both are shown; if only one creator is shown, put them in authors.
- Ignore non-book entries (lifetime achievement awards given to a person, statistics tables that only list years, "most awards" tables).
- source_text: copy the shortest piece of the wikitext line(s) the entry came from (max ~200 characters).
- Do not invent entries. If the page has nothing for those years, return an empty list."""


def _schema(category_ids, level_names):
    person = {
        "type": "object",
        "properties": {
            "first_name": {"type": "string"},
            "last_name": {"type": "string"},
        },
        "required": ["first_name", "last_name"],
        "additionalProperties": False,
    }
    return {
        "name": "award_entries",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category_id": {
                                "type": "integer",
                                "enum": list(category_ids),
                            },
                            "year": {"type": "integer"},
                            "title": {"type": "string"},
                            "authors": {"type": "array", "items": person},
                            "illustrators": {"type": "array", "items": person},
                            "award_level": {
                                "type": ["string", "null"],
                                "enum": list(level_names) + [None],
                            },
                            "level_text": {"type": "string"},
                            "source_text": {"type": "string"},
                        },
                        "required": [
                            "category_id",
                            "year",
                            "title",
                            "authors",
                            "illustrators",
                            "award_level",
                            "level_text",
                            "source_text",
                        ],
                        "additionalProperties": False,
                    },
                },
                "notes": {"type": "string"},
            },
            "required": ["entries", "notes"],
            "additionalProperties": False,
        },
    }


def build_user_prompt(
    page_title, category_contexts, level_names, wikitext, other_categories=()
):
    lines = [
        f"Wikipedia page: {page_title.replace('_', ' ')}",
        f"Allowed award_level names: {', '.join(level_names)}",
        "",
        "Categories to extract:",
    ]
    for c in category_contexts:
        lines.append(f"\n- category_id {c['id']}: {c['name']}")
        since = c.get("since")
        lines.append(f"  Extract: {'years >= ' + str(since) if since else 'ALL years'}")
        if c.get("section"):
            lines.append(f"  Linked section: {c['section']}")
        if c.get("notes"):
            lines.append(f"  Notes: {c['notes']}")
        if c.get("year_range"):
            lines.append(f"  Years already in our database: {c['year_range']}")
        if c.get("levels"):
            lines.append(f"  Award levels used: {c['levels']}")
        if c.get("examples"):
            lines.append("  Most recent entries we already have:")
            for e in c["examples"]:
                lines.append(f"    {e}")
    if other_categories:
        lines += ["", "Other categories on this page (skip their entries):"]
        lines += [f"- {name}" for name in other_categories]
    lines += ["", "=== WIKITEXT ===", wikitext]
    return "\n".join(lines)


class ExtractionError(Exception):
    pass


def extract_entries(
    page_title,
    category_contexts,
    level_names,
    wikitext,
    other_categories=(),
    api_key=None,
    model=None,
):
    """Call OpenAI and return (entries, notes, usage)."""
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ExtractionError("OPENAI_API_KEY is not set")
    category_ids = [c["id"] for c in category_contexts]
    model = model or DEFAULT_MODEL
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(
                    page_title,
                    category_contexts,
                    level_names,
                    wikitext,
                    other_categories,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": _schema(category_ids, level_names),
        },
    }
    if REASONING_EFFORT and model.startswith(("gpt-5", "o")):
        body["reasoning_effort"] = REASONING_EFFORT
    for attempt in (1, 2):  # one retry for timeouts / overload
        try:
            r = requests.post(
                OPENAI_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            if attempt == 1:
                time.sleep(10)
                continue
            raise ExtractionError(f"OpenAI request failed: {e}") from e
        if r.status_code in (429, 500, 502, 503, 504) and attempt == 1:
            time.sleep(20)
            continue
        break
    if r.status_code != 200:
        raise ExtractionError(f"OpenAI HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") not in ("stop", None):
        raise ExtractionError(f"OpenAI stopped early: {choice.get('finish_reason')}")
    msg = choice["message"]
    if msg.get("refusal"):
        raise ExtractionError(f"OpenAI refused: {msg['refusal']}")
    try:
        parsed = json.loads(msg["content"])
    except (TypeError, ValueError) as e:
        raise ExtractionError("OpenAI returned invalid JSON") from e
    return parsed["entries"], parsed.get("notes", ""), data.get("usage", {})
