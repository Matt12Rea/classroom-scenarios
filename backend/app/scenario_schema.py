"""Scenario definition format, normalisation and validation.

Shape produced by the teacher's scenario builder:

{
  "setting": "A high-school hallway between classes.",
  "objectives": ["Practice active listening", "De-escalate conflict"],
  "characters": [{"id": "jordan", "name": "Jordan", "role": "frustrated student",
                  "traits": "defensive but willing to talk if treated respectfully"}],
  "boundaries": ["No profanity"],
  "feedback_guidance": "Comment on whether the student listened before responding.",
  "start": "hallway",
  "nodes": {
    "hallway": {"title": "The confrontation", "prompt": "Jordan confronts you about a grade.",
                "character": "jordan", "min_turns": 2,
                "choices": [{"label": "Listen calmly", "next": "calm", "feedback": ""}],
                "ending": null},
    "calm": {"title": "Jordan relaxes", "prompt": "...", "character": "jordan", "choices": [],
             "ending": {"label": "Resolved", "type": "success", "feedback": "You listened first."}}
  }
}

The original engine's format (single "character", choices as a dict, ending as a
string) is still accepted and converted by normalize().
"""
import re
from collections import deque

ENDING_TYPES = ("success", "partial", "fail")
DEFAULT_BOUNDARIES = [
    "Stay in character and on the topic of the scenario",
    "No profanity, sexual content, or graphic violence",
    "Never give real-world instructions that could cause harm",
]


def slug(text: str, taken: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (text or "item").lower()).strip("_")[:40] or "item"
    s, i = base, 2
    while s in taken:
        s, i = f"{base}_{i}", i + 1
    return s


def normalize(d: dict) -> dict:
    """Return a clean copy in the current format. Never raises on bad input;
    problems are reported by validate()."""
    d = dict(d or {})
    out = {
        "setting": str(d.get("setting") or ""),
        "objectives": [str(o) for o in (d.get("objectives") or []) if str(o).strip()],
        "boundaries": [str(b) for b in (d.get("boundaries") or []) if str(b).strip()],
        "feedback_guidance": str(d.get("feedback_guidance") or ""),
        "start": str(d.get("start") or ""),
        "characters": [],
        "nodes": {},
    }
    chars = d.get("characters")
    if chars is None and isinstance(d.get("character"), dict):   # legacy single character
        chars = [{"id": "main", **d["character"]}]
    taken: set = set()
    for c in chars or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "") or slug(c.get("name", ""), taken)
        taken.add(cid)
        out["characters"].append({"id": cid, "name": str(c.get("name") or ""),
                                  "role": str(c.get("role") or ""),
                                  "traits": str(c.get("traits") or "")})
    default_char = out["characters"][0]["id"] if out["characters"] else ""

    for nid, n in (d.get("nodes") or {}).items():
        if not isinstance(n, dict):
            continue
        choices = n.get("choices") or []
        if isinstance(choices, dict):                            # legacy {"label": "next"}
            choices = [{"label": k, "next": v} for k, v in choices.items()]
        ending = n.get("ending")
        if isinstance(ending, str):                              # legacy "Good outcome"
            ending = {"label": ending, "type": "partial", "feedback": ""}
        if isinstance(ending, dict):
            ending = {"label": str(ending.get("label") or ""),
                      "type": ending.get("type") if ending.get("type") in ENDING_TYPES else "partial",
                      "feedback": str(ending.get("feedback") or "")}
        else:
            ending = None
        try:
            min_turns = max(0, min(20, int(n.get("min_turns") or 0)))
        except (TypeError, ValueError):
            min_turns = 0
        out["nodes"][str(nid)] = {
            "title": str(n.get("title") or nid),
            "prompt": str(n.get("prompt") or ""),
            "character": str(n.get("character") or default_char),
            "min_turns": min_turns,
            "choices": [] if ending else [
                {"label": str(c.get("label") or ""), "next": str(c.get("next") or ""),
                 "feedback": str(c.get("feedback") or "")}
                for c in choices if isinstance(c, dict)],
            "ending": ending,
        }
    return out


def validate(title: str, d: dict) -> dict:
    """REQ-3.1.6 / 3.1.8 / 3.3.7. Returns {"errors": [...], "warnings": [...]},
    each item {"field": "...", "message": "..."} so the UI can point at the field."""
    errors, warnings = [], []

    def err(field, msg):
        errors.append({"field": field, "message": msg})

    def warn(field, msg):
        warnings.append({"field": field, "message": msg})

    if not title.strip():
        err("title", "Give the scenario a title.")
    if not d["setting"].strip():
        err("setting", "Describe the setting so students know where they are.")
    if not d["objectives"]:
        err("objectives", "Add at least one learning objective.")
    if not d["characters"]:
        err("characters", "Add at least one AI character.")
    char_ids = set()
    for i, c in enumerate(d["characters"]):
        if not c["name"].strip():
            err(f"characters.{i}.name", f"Character {i + 1} needs a name.")
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

    for nid, n in nodes.items():
        f = f"nodes.{nid}"
        name = f"Scene “{n['title']}”"
        if not n["prompt"].strip():
            err(f"{f}.prompt", f"{name} needs a situation description.")
        if n["character"] and n["character"] not in char_ids:
            err(f"{f}.character", f"{name} uses a character that no longer exists.")
        if n["ending"]:
            if not n["ending"]["label"].strip():
                err(f"{f}.ending.label", f"{name} is an ending. Name the outcome (e.g. “Resolved”).")
            continue
        if not n["choices"]:
            err(f"{f}.choices", f"{name} is a dead end. Add a decision or mark it as an ending.")
        labels = set()
        for j, c in enumerate(n["choices"]):
            if not c["label"].strip():
                err(f"{f}.choices.{j}.label", f"{name}, decision {j + 1} needs text.")
            if c["label"] in labels:
                err(f"{f}.choices.{j}.label", f"{name} has two decisions with the same text.")
            labels.add(c["label"])
            if c["next"] not in nodes:
                err(f"{f}.choices.{j}.next", f"{name}, decision “{c['label'] or j + 1}” doesn't lead anywhere. Pick the next scene.")

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


EXAMPLE = normalize({
    "setting": "A high-school hallway just after the bell. You are a peer mentor.",
    "objectives": ["Practice active listening", "De-escalate a conflict"],
    "characters": [{"id": "jordan", "name": "Jordan", "role": "a frustrated classmate",
                    "traits": "Defensive and quick to interrupt, but opens up if treated with respect. "
                              "Thinks the history teacher graded their essay unfairly."}],
    "boundaries": ["Keep the conflict verbal; no threats", "Don't name real teachers or students"],
    "feedback_guidance": "Did the student listen and acknowledge Jordan's feelings before offering solutions?",
    "start": "hallway",
    "nodes": {
        "hallway": {"title": "The confrontation", "character": "jordan", "min_turns": 2,
                    "prompt": "Jordan storms up to you waving a graded essay with a D on it, saying it's unfair "
                              "and they're done with this class.",
                    "choices": [{"label": "Ask Jordan to walk you through what happened", "next": "listen",
                                 "feedback": "Inviting them to explain gives Jordan a sense of control."},
                                {"label": "Tell Jordan to calm down", "next": "escalate",
                                 "feedback": "Telling someone to calm down often makes them feel dismissed."}]},
        "listen": {"title": "Jordan explains", "character": "jordan", "min_turns": 2,
                   "prompt": "Jordan explains they worked hard and didn't understand the rubric.",
                   "choices": [{"label": "Suggest asking the teacher for a meeting together", "next": "resolved"},
                               {"label": "Say the teacher is probably right", "next": "escalate"}]},
        "escalate": {"title": "Things heat up", "character": "jordan", "min_turns": 1,
                     "prompt": "Jordan gets louder and other students start to stare.",
                     "choices": [{"label": "Apologise and ask what would help", "next": "listen"},
                                 {"label": "Walk away", "next": "walked"}]},
        "resolved": {"title": "A plan", "character": "jordan", "prompt": "Jordan agrees to go to office hours with you.",
                     "ending": {"label": "Conflict resolved", "type": "success",
                                "feedback": "You listened first and helped Jordan find a next step."}},
        "walked": {"title": "Walked away", "character": "jordan", "prompt": "Jordan is left upset in the hallway.",
                   "ending": {"label": "Unresolved", "type": "fail",
                              "feedback": "Walking away ended the conflict for you but not for Jordan."}},
    },
})
