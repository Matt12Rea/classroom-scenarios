"""Scenario definition format, normalisation and validation.

Shape produced by the scenario builder:

{
  "setting": "A community bank weighing 30-year fixed-rate mortgages.",
  "objectives": ["Explain interest-rate risk", "Recommend a way to manage it"],
  "characters": [{"id": "carol", "name": "Carol", "role": "the bank's president",
                  "traits": "practical, not an economist"}],
  "boundaries": ["No personal investment advice"],
  "feedback_guidance": "Did the student identify the maturity mismatch?",
  "start": "briefing",
  "nodes": {
    "briefing": {"title": "The question", "prompt": "Carol asks whether to write more fixed-rate loans.",
                 "characters": ["carol"], "character": "carol", "min_turns": 2, "wrap_after": 4,
                 "fallback": "",
                 "choices": [{"label": "Explained the interest-rate risk",
                              "signal": "The student explains that rising deposit costs squeeze fixed loan income.",
                              "next": "sound", "feedback": ""}],
                 "ending": null},
    "sound": {"title": "Sound advice", "prompt": "...", "characters": ["carol"], "choices": [],
              "ending": {"label": "Sound recommendation", "type": "success", "feedback": "You found the risk."}}
  }
}

A scene ("node") can have several characters present: "characters" lists their ids
in speaking order. "character" is always the first of them; it is kept so that
older code and sessions started before multi-character scenes keep working.

Students never see the choices. They are "paths": after each message the
application asks a judge model whether the student's own words show they have
taken one of them ("signal" describes what that looks like). "min_turns" is the
fewest messages before a scene can move on; "wrap_after" is the most, after
which the scene moves on (0 = no per-scene limit). At that point a path is
taken only if the student has actually done what it describes; otherwise the
scene's "fallback" path is taken: the path with that label, or, if blank, the
path whose branch leads to the worst ending (see fallback_choice).

Older formats (single "character", choices as a dict, ending as a string) are
still accepted and converted by normalize(). Choices without a "signal" are
matched on their label alone.

This module has no database or web imports, so it can be tested on its own.
"""
import re
from collections import deque

ENDING_TYPES = ("success", "partial", "fail")
DEFAULT_WRAP_AFTER = 8
MAX_SCENE_CAST = 4          # characters that can be present in one scene
MAX_SCENES = 80
MAX_PATHS_PER_SCENE = 8
DEFAULT_BOUNDARIES = [
    "Stay in character and on the topic of the scenario",
    "No profanity, sexual content, or graphic violence",
    "Never give real-world instructions that could cause harm",
]
NARRATOR = {"id": "narrator", "name": "Narrator", "role": "narrator", "traits": ""}


def slug(text: str, taken: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", str(text or "item").lower()).strip("_")[:40] or "item"
    s, i = base, 2
    while s in taken:
        s, i = f"{base}_{i}", i + 1
    return s


def _strings(value) -> list[str]:
    """A list of non-empty strings from whatever was sent (a list, one string, or nothing)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value if v is not None and str(v).strip()]


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def normalize(d: dict) -> dict:
    """Return a clean copy in the current format. Never raises on bad input;
    problems are reported by validate()."""
    d = dict(d) if isinstance(d, dict) else {}
    out = {
        "setting": str(d.get("setting") or ""),
        "objectives": _strings(d.get("objectives")),
        "boundaries": _strings(d.get("boundaries")),
        "feedback_guidance": str(d.get("feedback_guidance") or ""),
        "start": str(d.get("start") or ""),
        "characters": [],
        "nodes": {},
    }
    chars = d.get("characters")
    if chars is None and isinstance(d.get("character"), dict):   # legacy single character
        chars = [{"id": "main", **d["character"]}]
    taken: set = set()
    for c in chars if isinstance(chars, list) else []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "") or slug(c.get("name", ""), taken)
        taken.add(cid)
        out["characters"].append({"id": cid, "name": str(c.get("name") or "").strip()[:120],
                                  "role": str(c.get("role") or "").strip(),
                                  "traits": str(c.get("traits") or "")})
    default_char = out["characters"][0]["id"] if out["characters"] else ""

    nodes = d.get("nodes")
    for nid, n in list(nodes.items())[:MAX_SCENES] if isinstance(nodes, dict) else []:
        if not isinstance(n, dict):
            continue
        choices = n.get("choices") or []
        if isinstance(choices, dict):                            # legacy {"label": "next"}
            choices = [{"label": k, "next": v} for k, v in choices.items()]
        if not isinstance(choices, list):
            choices = []
        ending = n.get("ending")
        if isinstance(ending, str):                              # legacy "Good outcome"
            ending = {"label": ending, "type": "partial", "feedback": ""}
        if isinstance(ending, dict):
            ending = {"label": str(ending.get("label") or "").strip()[:200],
                      "type": ending.get("type") if ending.get("type") in ENDING_TYPES else "partial",
                      "feedback": str(ending.get("feedback") or "")}
        else:
            ending = None

        # Who is present: the new "characters" list, or the older single "character".
        raw_cast = n.get("characters")
        if isinstance(raw_cast, str):
            raw_cast = [raw_cast]
        if not isinstance(raw_cast, list) or not raw_cast:
            raw_cast = [n.get("character")] if n.get("character") else []
        cast: list[str] = []
        for c in raw_cast:
            c = str(c or "")
            if c and c not in cast:
                cast.append(c)
        cast = cast[:MAX_SCENE_CAST]
        if not cast and default_char:
            cast = [default_char]

        out["nodes"][str(nid)] = {
            "title": str(n.get("title") or nid).strip()[:200],
            "prompt": str(n.get("prompt") or ""),
            "characters": cast,
            "character": cast[0] if cast else "",
            "min_turns": _int(n.get("min_turns") or 0, 0, 0, 20),
            "wrap_after": _int(n.get("wrap_after", DEFAULT_WRAP_AFTER), DEFAULT_WRAP_AFTER, 0, 50),
            "fallback": "" if ending else str(n.get("fallback") or "").strip(),
            "choices": [] if ending else [
                {"label": str(c.get("label") or "").strip()[:200], "signal": str(c.get("signal") or ""),
                 "next": str(c.get("next") or ""), "feedback": str(c.get("feedback") or "")}
                for c in choices[:MAX_PATHS_PER_SCENE] if isinstance(c, dict)],
            "ending": ending,
        }
    return out


def scene_cast(d: dict, node_id: str) -> list[dict]:
    """The characters present in a scene, in speaking order. Always at least one, so
    callers never have to handle an empty scene. Works on old snapshots that only have
    a single "character" per scene."""
    node = (d.get("nodes") or {}).get(node_id) or {}
    by_id = {c["id"]: c for c in d.get("characters") or []}
    ids = node.get("characters") or ([node["character"]] if node.get("character") else [])
    cast = [by_id[i] for i in ids if i in by_id]
    if cast:
        return cast
    return list((d.get("characters") or [])[:1]) or [dict(NARRATOR)]


OUTCOME_RANK = {"fail": 0, "partial": 1, "success": 2}


def worst_outcome_from(d: dict, start: str) -> int:
    """Rank of the worst ending reachable from a scene (fail 0, partial 1, success 2)."""
    nodes, seen, q, worst = d["nodes"], {start}, deque([start]), None
    while q:
        n = nodes.get(q.popleft())
        if not n:
            continue
        if n.get("ending"):
            r = OUTCOME_RANK.get(n["ending"].get("type"), 1)
            worst = r if worst is None else min(worst, r)
        for c in n.get("choices", []):
            if c.get("next") in nodes and c["next"] not in seen:
                seen.add(c["next"])
                q.append(c["next"])
    return 1 if worst is None else worst


def fallback_choice(d: dict, node_id: str) -> dict | None:
    """The path a scene takes when it wraps up and the student hasn't clearly taken any
    path: the one the instructor chose, or the path that can lead to the worst ending
    (the last such path on a tie). Not engaging should never be rewarded."""
    n = d["nodes"][node_id]
    choices = [c for c in n.get("choices", []) if c.get("next") in d["nodes"]]
    if not choices:
        return None
    chosen = next((c for c in choices if n.get("fallback") and c["label"] == n["fallback"]), None)
    if chosen:
        return chosen
    ranked = [(worst_outcome_from(d, c["next"]), -i, c) for i, c in enumerate(choices)]
    return min(ranked, key=lambda x: (x[0], x[1]))[2]


def validate(title: str, d: dict) -> dict:
    """REQ-3.1.6 / 3.1.8 / 3.3.7. Returns {"errors": [...], "warnings": [...]},
    each item {"field": "...", "message": "..."} so the UI can point at the field.
    Expects a definition that has been through normalize()."""
    errors, warnings = [], []

    def err(field, msg):
        errors.append({"field": field, "message": msg})

    def warn(field, msg):
        warnings.append({"field": field, "message": msg})

    if not str(title or "").strip():
        err("title", "Give the scenario a title.")
    if not d["setting"].strip():
        err("setting", "Describe the setting so students know where they are.")
    if not d["objectives"]:
        err("objectives", "Add at least one learning objective.")
    if not d["characters"]:
        err("characters", "Add at least one AI character.")
    char_ids, names = set(), set()
    for i, c in enumerate(d["characters"]):
        if not c["name"].strip():
            err(f"characters.{i}.name", f"Character {i + 1} needs a name.")
        elif c["name"].strip().lower() in names:
            err(f"characters.{i}.name", f"Two characters are called “{c['name']}”. Give each a different name "
                                        "so students can tell who is speaking.")
        names.add(c["name"].strip().lower())
        if not c["role"].strip():
            err(f"characters.{i}.role", f"Say who {c['name'] or f'character {i + 1}'} is (their role).")
        if c["id"] in char_ids:
            err(f"characters.{i}.id", "Two characters share the same id.")
        char_ids.add(c["id"])

    nodes = d["nodes"]
    if not nodes:
        err("nodes", "Add at least one scene.")
        return {"errors": errors, "warnings": warnings}
    if d["start"] not in nodes:
        err("start", "Choose which scene the scenario starts with.")

    in_a_scene: set = set()
    for nid, n in nodes.items():
        f = f"nodes.{nid}"
        name = f"Scene “{n['title']}”"
        if len(nid) > 64:
            err(f, f"{name} has an internal id that is too long. Delete the scene and add it again.")
        cast = n.get("characters") or ([n["character"]] if n.get("character") else [])
        in_a_scene.update(cast)
        if not n["prompt"].strip():
            err(f"{f}.prompt", f"{name} needs a description of what's happening.")
        if d["characters"] and not cast:
            err(f"{f}.characters", f"{name} has no one in it. Choose at least one character.")
        elif any(c not in char_ids for c in cast):
            err(f"{f}.characters", f"{name} includes a character that no longer exists. Choose who is in the scene.")
        if n["ending"]:
            if not n["ending"]["label"].strip():
                err(f"{f}.ending.label", f"{name} is an ending. Name the outcome (e.g. “Resolved”).")
            continue
        if not n["choices"]:
            err(f"{f}.choices", f"{name} doesn't lead anywhere. Add a path to another scene, or make it an ending.")
        labels = set()
        for j, c in enumerate(n["choices"]):
            if not c["label"].strip():
                err(f"{f}.choices.{j}.label", f"{name}, path {j + 1} needs a name.")
            if c["label"] in labels:
                err(f"{f}.choices.{j}.label", f"{name} has two paths with the same name.")
            labels.add(c["label"])
            if c["next"] not in nodes:
                err(f"{f}.choices.{j}.next", f"{name}, path “{c['label'] or j + 1}” doesn't lead anywhere. Pick the next scene.")
            if c["label"].strip() and not c["signal"].strip():
                warn(f"{f}.choices.{j}.signal", f"{name}, path “{c['label']}”: describe what the student says or "
                                                "does to take it. Without that, it's matched on its name alone.")
        if n["fallback"] and n["fallback"] not in labels:
            err(f"{f}.fallback", f"{name}: the path to take when nothing is clear no longer exists. Pick another.")
        if n["wrap_after"] and n["wrap_after"] < max(1, n["min_turns"]):
            err(f"{f}.wrap_after", f"{name} wraps up before students reach the minimum number of messages. "
                                   "Raise the maximum or lower the minimum.")

    for i, c in enumerate(d["characters"]):
        if c["id"] not in in_a_scene and c["name"].strip():
            warn(f"characters.{i}", f"{c['name']} isn't in any scene yet.")

    # Reachability: every scene should be reachable, and an ending reachable from start.
    if d["start"] in nodes:
        seen, q = {d["start"]}, deque([d["start"]])
        while q:
            for c in nodes[q.popleft()]["choices"]:
                if c["next"] in nodes and c["next"] not in seen:
                    seen.add(c["next"])
                    q.append(c["next"])
        for nid in nodes:
            if nid not in seen:
                warn(f"nodes.{nid}", f"Scene “{nodes[nid]['title']}” can't be reached from the start.")
        if not any(nodes[n]["ending"] for n in seen):
            err("nodes", "No ending can be reached from the start scene. Students could never finish.")
        # Scenes from which no ending is reachable (endless loops).
        can_finish = {n for n in nodes if nodes[n]["ending"]}
        changed = True
        while changed:
            changed = False
            for nid, n in nodes.items():
                if nid not in can_finish and any(c["next"] in can_finish for c in n["choices"]):
                    can_finish.add(nid)
                    changed = True
        for nid in seen - can_finish:
            if not nodes[nid]["ending"] and nodes[nid]["choices"]:   # dead ends are already errors
                warn(f"nodes.{nid}", f"From scene “{nodes[nid]['title']}” students can loop forever without reaching an ending.")
    if not d["boundaries"]:
        warn("boundaries", "No boundaries set. The standard safety boundaries will still apply.")
    return {"errors": errors, "warnings": warnings}


# Money and Banking: explain interest-rate risk to a community bank's president.
EXAMPLE = normalize({
    "setting": "Prairie State Community Bank, a small bank in central Iowa, in March. You are a junior analyst "
               "who took Money and Banking last year. The bank funds itself mostly with savings deposits and "
               "1-year CDs. Inflation has run near 4.5% for six months and the Federal Reserve has signalled more "
               "rate increases. A local home builder wants the bank to offer its buyers 30-year fixed-rate "
               "mortgages at 6%.",
    "objectives": ["Explain the interest-rate risk of funding long-term fixed-rate loans with short-term deposits",
                   "Connect expected Federal Reserve policy to a bank's net interest margin",
                   "Make an economic recommendation a non-economist can act on"],
    "characters": [
        {"id": "carol", "name": "Carol Brennan", "role": "the bank's president",
         "traits": "Practical, thirty years in community banking, not an economist. Wants plain English and a "
                   "recommendation she can take to the loan committee. Glazes over at jargon; is persuaded by a "
                   "concrete numerical example. Worried about losing the builder's business to the credit union."}],
    "boundaries": ["Stay within the banking scenario; no personal investment advice",
                   "Use fictional institutions and people"],
    "feedback_guidance": "Did the student identify the maturity mismatch (short-term deposits funding 30-year fixed "
                         "loans), show with numbers how rising rates squeeze the net interest margin, and propose a "
                         "realistic way to manage the risk rather than refusing to lend?",
    "start": "briefing",
    "nodes": {
        "briefing": {"title": "The president's question", "character": "carol", "min_turns": 2, "wrap_after": 4,
                     "prompt": "Carol waves you into her office. \"Rates are going up, so a 6% fixed mortgage sounds "
                               "like a great deal for us. Should we write as many of these as we can?\"",
                     "choices": [
                         {"label": "Explained the bank's interest-rate risk",
                          "signal": "The student explains that the bank pays short-term rates on deposits and CDs "
                                    "that will rise if the Fed raises rates, while the mortgage keeps earning a "
                                    "fixed 6% for 30 years, so the spread (net interest margin) shrinks or turns "
                                    "negative. Naming the maturity or duration mismatch, or giving a numeric "
                                    "example, counts.",
                          "next": "options",
                          "feedback": "Rising rates hurt a lender that borrows short and lends long. Spotting that "
                                      "is the core of bank interest-rate risk."},
                         {"label": "Endorsed writing more fixed-rate loans",
                          "signal": "The student agrees the bank should write many 30-year fixed loans at 6%, or "
                                    "argues that rising rates make fixed-rate loans better for the bank, without "
                                    "raising the cost of the bank's own funding.",
                          "next": "squeeze"}]},
        "options": {"title": "So what do we do?", "character": "carol", "min_turns": 2, "wrap_after": 4,
                    "prompt": "Carol leans back. \"All right, I follow. But if we don't offer something, the builder "
                              "takes his buyers to the credit union. What do you recommend?\"",
                    "choices": [
                        {"label": "Recommended a way to manage the risk",
                         "signal": "The student recommends a concrete way to keep lending while managing the risk, "
                                   "such as adjustable-rate mortgages, pricing the fixed rate higher to reflect "
                                   "expected rate rises, selling the fixed-rate loans on the secondary market, or "
                                   "funding them with longer-term liabilities, and explains why it helps.",
                         "next": "sound"},
                        {"label": "Recommended stopping mortgage lending",
                         "signal": "The student says the bank should stop offering mortgages, with no alternative "
                                   "that keeps the business.",
                         "next": "refused"}]},
        "squeeze": {"title": "Eighteen months later", "character": "carol", "min_turns": 2, "wrap_after": 4,
                    "prompt": "Eighteen months on, the bank is paying 7% on new CDs while the mortgage book still "
                              "earns 6%. Carol drops a report on your desk. \"We're losing money on these loans. "
                              "What happened?\"",
                    "choices": [
                        {"label": "Diagnosed the maturity mismatch",
                         "signal": "The student explains that deposit and CD costs rose with market rates while the "
                                   "fixed mortgage income did not, producing a negative spread, and suggests how "
                                   "to price or structure future loans differently.",
                         "next": "lesson"},
                        {"label": "Blamed the wrong cause",
                         "signal": "The student attributes the losses to something else, such as borrower defaults, "
                                   "the builder, or bad luck, or can't explain them.",
                         "next": "losses"}]},
        "sound": {"title": "To the loan committee", "character": "carol",
                  "prompt": "Carol takes your recommendation to the loan committee, which approves it with your "
                            "numbers attached.",
                  "ending": {"label": "Sound recommendation", "type": "success",
                             "feedback": "You found the risk, explained it in terms Carol could use, and kept the "
                                         "bank lending. That's applied monetary economics."}},
        "refused": {"title": "Playing it too safe", "character": "carol",
                    "prompt": "The bank stops offering mortgages. The builder moves his buyers to the credit union.",
                    "ending": {"label": "Safe but costly", "type": "partial",
                               "feedback": "You avoided the interest-rate risk, but gave up the interest income "
                                           "and the customer relationship. Every option has an opportunity cost; "
                                           "the better answer manages the risk instead of avoiding the business."}},
        "lesson": {"title": "Learning the hard way", "character": "carol",
                   "prompt": "Carol shifts new lending to adjustable rates. The old loans keep losing money until "
                             "they're paid off.",
                   "ending": {"label": "Diagnosed, too late", "type": "partial",
                              "feedback": "Your diagnosis was right, but the risk was predictable from the Fed's "
                                          "signals at the time the loans were made."}},
        "losses": {"title": "Unexplained losses", "character": "carol",
                   "prompt": "The examiners arrive before anyone at the bank can explain the losses.",
                   "ending": {"label": "Risk not understood", "type": "fail",
                              "feedback": "The losses came from rising funding costs against fixed income, not "
                                          "defaults. Review how a bank's net interest margin responds to rate "
                                          "changes."}},
    },
})
