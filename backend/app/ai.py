"""Claude integration (REQ-3.2.3.x). The only module that talks to the AI service.
The API key lives only on the server (environment variable, or encrypted in the
database when set from the admin dashboard) and is never sent to browsers.

What is said to the AI and how its answers are read lives in dialogue.py (plain
functions, no network). This module only sends and receives."""
import json
import logging
import re
import threading
import time
from dataclasses import dataclass

from . import config, settings_store
# Re-exported so existing callers (and tests) can keep using ai.<name>.
from .dialogue import (build_system_prompt, character_for, debrief_prompt, judge_request,  # noqa: F401
                       parse_judgement, parse_reply, tidy_history)

log = logging.getLogger("aicss.ai")


@dataclass
class AIResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0


# ------------------------------------------------------------------ clients --
# What an administrator sees for each kind of failure (Admin > AI connection).
ERROR_HELP = {
    "auth": "The API key was rejected. It may have been revoked or mistyped. Add a new key.",
    "permission": "The API key doesn't have permission to use this model.",
    "billing": "The Anthropic account is out of credit. Add credit or turn on auto-reload in the Anthropic Console.",
    "rate_limit": "Too many requests for the account's rate limit. Replies will resume shortly; "
                  "if this keeps happening, raise the limit in the Anthropic Console.",
    "overloaded": "The AI service is temporarily overloaded. It usually recovers within minutes.",
    "timeout": "The AI service took too long to answer.",
    "network": "The server couldn't reach the AI service. Check the server's outbound internet access.",
    "model": "The configured model name wasn't recognised. Pick another model.",
    "bad_request": "The AI service rejected the request.",
    "unknown": "The AI service returned an unexpected error.",
}


def classify(e: Exception) -> str:
    """Map an SDK exception to one of ERROR_HELP's keys, without logging content."""
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        return "auth"
    if isinstance(e, anthropic.PermissionDeniedError):
        return "permission"
    if isinstance(e, anthropic.NotFoundError):
        return "model"
    if isinstance(e, anthropic.RateLimitError):
        return "rate_limit"
    if isinstance(e, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(e, anthropic.APIConnectionError):
        return "network"
    status = getattr(e, "status_code", None)
    msg = str(getattr(e, "message", "") or e).lower()
    if "credit balance" in msg or "billing" in msg or status == 402:
        return "billing"
    if status in (500, 502, 503, 529) or "overloaded" in msg:
        return "overloaded"
    if isinstance(e, anthropic.BadRequestError):
        return "bad_request"
    return "unknown"


class AIUnavailable(Exception):
    def __init__(self, kind: str = "unknown"):
        super().__init__(kind)
        self.kind = kind


class ClaudeEngine:
    name = "claude"

    def __init__(self, api_key: str, model: str, review_model: str):
        import anthropic  # imported lazily so mock mode needs no SDK
        self._anthropic = anthropic
        self.model, self.review_model = model, review_model
        # The SDK retries connection errors, 408/409/429 and 5xx with exponential
        # backoff, which rides out short outages without the student noticing.
        self.client = anthropic.Anthropic(api_key=api_key, timeout=config.AI_TIMEOUT_SECONDS,
                                          max_retries=config.AI_MAX_RETRIES)

    def _call(self, track: bool = True, **kw) -> AIResult:
        t0 = time.monotonic()
        try:
            msg = self.client.messages.create(**kw)
        except self._anthropic.APIError as e:          # includes timeouts/connection errors
            kind = classify(e)
            log.warning("Claude API error: %s (%s)", type(e).__name__, kind)   # no student data in logs
            if track:
                settings_store.record_ai_result(False, kind)
            raise AIUnavailable(kind) from e
        except Exception as e:                         # anything else the SDK or network layer throws
            log.error("Unexpected error calling Claude: %s", type(e).__name__)
            if track:
                settings_store.record_ai_result(False, "unknown")
            raise AIUnavailable("unknown") from e
        text = "".join(getattr(b, "text", "") or "" for b in (msg.content or [])
                       if getattr(b, "type", "") == "text").strip()
        u = getattr(msg, "usage", None)
        latency = int((time.monotonic() - t0) * 1000)
        if track:
            settings_store.record_ai_result(True, latency_ms=latency)
        return AIResult(text, getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0,
                        getattr(u, "cache_read_input_tokens", 0) or 0, latency)

    def reply(self, system, history, student_text, cast=None) -> AIResult:
        """history: earlier turns as {"role", "content"}. cast: the characters present
        (unused here; the system prompt already names them)."""
        extra = 120 * max(0, len(cast or []) - 1)       # room for a second voice
        return self._call(model=self.model, max_tokens=config.MAX_OUTPUT_TOKENS + extra,
                          system=system,
                          messages=tidy_history(history + [{"role": "user", "content": student_text}]))

    def debrief(self, prompt: str) -> AIResult:
        return self._call(model=self.review_model, max_tokens=350,
                          messages=[{"role": "user", "content": prompt}])

    def judge(self, system: str, user: str) -> str:
        return self._call(model=self.review_model, max_tokens=200, system=system,
                          messages=[{"role": "user", "content": user}]).text

    def review(self, student_text: str, ai_text: str) -> dict | None:
        from .moderation import REVIEW_PROMPT
        try:
            r = self._call(model=self.review_model, max_tokens=150, system=REVIEW_PROMPT,
                           messages=[{"role": "user", "content":
                                      f"<student>{student_text}</student>\n<ai>{ai_text}</ai>"}])
        except AIUnavailable:
            return None
        m = re.search(r"\{.*\}", r.text, re.S)
        try:
            data = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def ping(self) -> AIResult:
        """Smallest possible request, used by "Test connection". Contains no student data."""
        return self._call(track=False, model=self.model, max_tokens=5,
                          messages=[{"role": "user", "content": "Reply with the word ready."}])


class MockEngine:
    """Stand-in used when no API key is configured. Lets you click through every
    screen and run the tests for free. Replies are clearly generic."""
    name = "mock"
    LINES = [
        "I hear you, but I'm still not sure about this.",
        "Okay... go on. What do you think I should do?",
        "That's not really what I expected you to say.",
        "Fine. I'm listening, but this better be worth it.",
        "Hm. Maybe you have a point there.",
        "Why should I trust you on that?",
    ]
    SECOND_LINES = [
        "I was wondering the same thing.",
        "Hold on, I'm not sure I agree.",
        "Can you explain that part again?",
    ]

    def reply(self, system, history, student_text, cast=None) -> AIResult:
        if "fail_ai" in student_text:              # lets tests simulate an outage
            raise AIUnavailable("overloaded")
        # Deterministic: the line depends on how far the conversation has got.
        n = sum(1 for m in history if m.get("role") == "user")
        line = self.LINES[n % len(self.LINES)]
        if not cast or len(cast) < 2:
            return AIResult(line, latency_ms=5)
        first = cast[n % len(cast)]
        out = [f"{first['name']}: {line}"]
        if n % 2 == 1:                              # every other turn a second character joins in
            second = cast[(n + 1) % len(cast)]
            out.append(f"{second['name']}: {self.SECOND_LINES[n % len(self.SECOND_LINES)]}")
        return AIResult("\n".join(out), latency_ms=5)

    STOP = set("the a an and or to of in on for with that this they them their your you about what "
               "from before after into than then when have has had been were was are is it its".split())

    @classmethod
    def _words(cls, text: str) -> set:
        return {w[:6] for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4 and w not in cls.STOP}

    def judge(self, system: str, user: str) -> str:
        """Word-overlap stand-in for Claude: a path is taken when the student's lines share
        enough words with its name and description."""
        none = '{"path": null, "confidence": 0, "reason": "No path matched yet."}'
        found = re.search(r"<paths>\n(.*?)\n</paths>", user, re.S)
        block = re.search(r"<transcript>\n?(.*?)\n?</transcript>", user, re.S)
        if not found or not block:
            return none
        paths = found.group(1).splitlines()
        said = self._words(" ".join(ln[len("Student: "):] for ln in block.group(1).splitlines()
                                    if ln.startswith("Student: ")))
        best, best_score = None, 0
        for i, line in enumerate(paths):
            words = self._words(line.split(". ", 1)[-1])
            score = len(words & said)
            if score >= min(2, len(words)) and score > best_score:
                best, best_score = i, score
        if best is None:
            return none
        return json.dumps({"path": best + 1, "confidence": 0.9,
                           "reason": f"Demo mode: the student's words matched path {best + 1}."})

    def debrief(self, prompt: str) -> AIResult:
        return AIResult("")      # empty → caller falls back to the teacher's written feedback

    def review(self, student_text, ai_text):
        return None

    def ping(self) -> AIResult:
        return AIResult("ready", latency_ms=1)


_engine = None
_engine_fp = ""
_engine_lock = threading.Lock()


def engine():
    """The engine for the current settings. Rebuilt automatically when an
    administrator changes the key, model or mode, with no restart needed.
    Raises AIUnavailable if the engine can't be set up."""
    global _engine, _engine_fp
    s = settings_store.ai_settings()
    fp = f"{s.fingerprint}|{s.model}|{s.review_model}"
    if _engine is None or fp != _engine_fp:
        with _engine_lock:
            if _engine is None or fp != _engine_fp:
                try:
                    built = (ClaudeEngine(s.api_key, s.model, s.review_model) if s.mode == "claude"
                             else MockEngine())
                except Exception as e:      # e.g. the anthropic package is missing or the key is malformed
                    log.error("Couldn't set up the AI engine: %s", type(e).__name__)
                    settings_store.record_ai_result(False, "unknown")
                    raise AIUnavailable("unknown") from e
                _engine, _engine_fp = built, fp
                log.info("AI engine: %s (%s, key from %s)", _engine.name, s.model, s.source)
    return _engine


def test_key(api_key: str, model: str) -> tuple[bool, str, int | None]:
    """Try a key before saving it. Returns (ok, error kind, latency ms)."""
    try:
        r = ClaudeEngine(api_key, model, model).ping()
        return True, "", r.latency_ms
    except AIUnavailable as e:
        return False, e.kind, None
    except Exception as e:                  # the SDK refused the key before sending anything
        log.error("Couldn't test the AI key: %s", type(e).__name__)
        return False, "unknown", None
