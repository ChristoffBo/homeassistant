#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat + RAG + optional web fallback)
# - Default: offline LLM chat with RAG injection
# - Web mode if wake words are present OR offline LLM+RAG fails OR offline text says "cannot search / please verify / unsure"
# - Topic aware routing:
#     * entertainment: IMDb/Wikipedia/RT/Metacritic (Reddit only vetted movie subs, not for fact queries)
#     * tech/dev: GitHub + StackExchange + Reddit tech subs
#     * sports: F1/ESPN/FIFA official; Reddit excluded for fact queries
#     * general: Wikipedia/Britannica/Biography/History
# - Filters: English-only, block junk/low-signal domains, require keyword overlap
# - Ranking: authority + keyword overlap + strong recency for facts
# - Fallbacks: summarizer fallback + direct snippet mode for fact queries
# - Integrations: DuckDuckGo, Wikipedia, Reddit (vetted), GitHub (tech)
# - Free, no-register APIs only
# - Human behavior heuristics: prefer clear facts, recency, multiple perspectives, avoid spammy/repetitive sources

import os, re, json, time, html, requests, datetime, traceback
from typing import Dict, List, Tuple, Optional
from urllib.parse import quote as _urlquote

DEBUG = bool(os.environ.get("JARVIS_DEBUG"))

# ----------------------------
# LLM bridge
# ----------------------------
try:
    import llm_client as _LLM
except Exception:
    _LLM = None

def _llm_ready() -> bool:
    return _LLM is not None and hasattr(_LLM, "chat_generate")

def _chat_offline_singleturn(user_msg: str, max_new_tokens: int = 256) -> str:
    if not _llm_ready():
        return ""
    try:
        return _LLM.chat_generate(
            messages=[{"role": "user", "content": user_msg}],
            system_prompt="",
            max_new_tokens=max_new_tokens,
        ) or ""
    except Exception:
        return ""

def _chat_offline_summarize(question: str, notes: str, max_new_tokens: int = 320) -> str:
    if not _llm_ready():
        return ""
    sys_prompt = (
        "You are a concise synthesizer. Using only the provided bullet notes, write a clear 4–6 sentence answer. "
        "Prefer concrete facts & dates. Avoid speculation. If info is conflicting, note it briefly. "
        "Rank recent and authoritative sources higher. Respond like a human researcher would: factual, relevant, helpful."
    )
    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"Question: {question.strip()}\n\nNotes:\n{notes.strip()}\n\nWrite the answer now."},
    ]
    try:
        return _LLM.chat_generate(messages=msgs, system_prompt="", max_new_tokens=max_new_tokens) or ""
    except Exception:
        return ""

# ----------------------------
# RAG bridge
# ----------------------------
try:
    import rag
except Exception:
    rag = None

def _chat_offline_with_rag(user_msg: str, max_new_tokens: int = 256) -> str:
    """Inject RAG context into offline chat."""
    if not _llm_ready() or rag is None or not hasattr(rag, "inject_context"):
        return ""
    try:
        ctx = rag.inject_context(user_msg, top_k=5)
        if not ctx:
            return ""
        prompt = f"Use this context if relevant:\n{ctx}\n\nQuestion: {user_msg}"
        return _LLM.chat_generate(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="",
            max_new_tokens=max_new_tokens,
        ) or ""
    except Exception:
        return ""

# ----------------------------
# Topic detection
# ----------------------------
_TECH_KEYS = re.compile(r"\b(api|bug|error|exception|stacktrace|repo|github|docker|k8s|kubernetes|linux|debian|ubuntu|arch|kernel|python|node|golang|go|java|c\+\+|rust|mysql|postgres|sql|ssh|tls|ssl|dns|vpn|proxmox|homeassistant|zimaos|opnsense)\b", re.I)
_ENT_KEYS  = re.compile(r"\b(movie|film|actor|actress|imdb|rotten|metacritic|trailer|box office|release|cast|director)\b", re.I)
_SPORT_KEYS = re.compile(r"\b(f1|formula 1|grand prix|premier league|nba|nfl|fifa|world cup|uefa|olympics|tennis|atp|wta|golf|pga)\b", re.I)

def _detect_intent(q: str) -> str:
    ql = (q or "").lower()
    if _TECH_KEYS.search(ql):
        return "tech"
    if _SPORT_KEYS.search(ql):
        return "sports"
    if _ENT_KEYS.search(ql) or re.search(r"\b(last|latest)\b.*\b(movie|film)\b", ql):
        return "entertainment"
    if re.search(r"\b(movie|film)\b", ql):
        return "entertainment"
    return "general"

# ----------------------------
# Helpers & filters
# ----------------------------
_AUTHORITY_COMMON = [
    "wikipedia.org", "britannica.com", "biography.com", "history.com"
]
_AUTHORITY_ENT = [
    "imdb.com", "rottentomatoes.com", "metacritic.com", "boxofficemojo.com"
]
_AUTHORITY_SPORTS = [
    "espn.com", "fifa.com", "nba.com", "nfl.com", "olympics.com", "formula1.com",
    "autosport.com", "motorsport.com", "the-race.com"
]
_AUTHORITY_TECH = [
    "github.com", "gitlab.com", "stackoverflow.com", "superuser.com", "serverfault.com",
    "unix.stackexchange.com", "askubuntu.com", "archlinux.org", "kernel.org",
    "docs.python.org", "nodejs.org", "golang.org",
    "learn.microsoft.com", "answers.microsoft.com", "support.microsoft.com",
    "man7.org", "linux.org"
]

_REDDIT_ALLOW_ENT = {"movies","TrueFilm","MovieDetails","tipofmytongue","criterion","oscarrace"}
_REDDIT_ALLOW_TECH = {"learnpython","python","programming","sysadmin","devops","linux","selfhosted","homelab","docker","kubernetes","opensource","techsupport","homeassistant","homeautomation"}

_DENY_DOMAINS = [
    "zhihu.com","baidu.com","pinterest.","quora.com","tumblr.com",
    "vk.com","weibo.","4chan","8kun","/forum","forum.","boards.",
    "linktr.ee","tiktok.com","facebook.com","notebooklm.google.com"
]

def _tokenize(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2]

def _keyword_overlap(q: str, title: str, snippet: str, min_hits: int = 2) -> bool:
    qk = set(_tokenize(q))
    tk = set(_tokenize((title or "") + " " + (snippet or "")))
    stop = {"where","what","who","when","which","the","and","for","with","from","into",
            "about","this","that","your","you","are","was","were","have","has","had",
            "movie","film","films","videos","watch","code","codes","list","sale","sell","selling"}
    qk = {w for w in qk if w not in stop}
    return len(qk & tk) >= min_hits

def _domain_of(url: str) -> str:
    try:
        return re.sub(r"^www\.", "", re.findall(r"https?://([^/]+)/?", url, re.I)[0].lower())
    except Exception:
        return ""

def _is_deny_domain(url: str) -> bool:
    d = _domain_of(url)
    test = d + url.lower()
    return any(bad in test for bad in _DENY_DOMAINS)

def _is_authority(url: str, vertical: str) -> bool:
    d = _domain_of(url)
    pool = set(_AUTHORITY_COMMON)
    if vertical == "entertainment":
        pool.update(_AUTHORITY_ENT)
    elif vertical == "sports":
        pool.update(_AUTHORITY_SPORTS)
    elif vertical == "tech":
        pool.update(_AUTHORITY_TECH)
    return any(d.endswith(ad) for ad in pool)

def _is_english_text(text: str, max_ratio: float = 0.2) -> bool:
    if not text:
        return True
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    return (non_ascii / max(1, len(text))) <= max_ratio

def _is_junk_result(title: str, snippet: str, url: str, q: str, vertical: str) -> bool:
    if not title and not snippet:
        return True
    if _is_deny_domain(url):
        return True
    text = (title or "") + " " + (snippet or "")
    if not _is_english_text(text, max_ratio=0.2):
        return True
    if not _keyword_overlap(q, title, snippet, min_hits=2):
        return True
    # Kill commerce / resale / code-list spam
    if re.search(r"\b(price|venmo|cashapp|zelle|paypal|gift\s*card|promo\s*code|digital\s*code|$[0-9])\b", text, re.I):
        return True
    # Community-source gating
    if "reddit.com" in url.lower():
        m = re.search(r"/r/([A-Za-z0-9_]+)/", url)
        sub = (m.group(1).lower() if m else "")
        if vertical == "entertainment":
            if sub not in {s.lower() for s in _REDDIT_ALLOW_ENT}:
                return True
        elif vertical == "tech":
            if sub not in {s.lower() for s in _REDDIT_ALLOW_TECH}:
                return True
        elif vertical == "sports":
            if sub not in {"formula1","motorsports"}:
                return True
    return False

_CURRENT_YEAR = datetime.datetime.utcnow().year

# (web search code continues unchanged…)

# ----------------------------
# Public entry
# ----------------------------
def handle_message(source: str, text: str) -> str:
    q = (text or "").strip()
    if not q:
        return ""
    try:
        if DEBUG: print("IN_MSG:", q)

        # Try RAG first
        ans = _chat_offline_with_rag(q, max_new_tokens=256)

        # Fallback: plain offline if no RAG hit
        if not ans:
            ans = _chat_offline_singleturn(q, max_new_tokens=256)

        clean_ans = _clean_text(ans)
        if DEBUG: print("OFFLINE+RAG_ANS:", repr(clean_ans))

        offline_unknown_markers = {
            "i don't know.", "i dont know", "(no reply)", "unknown", "no idea",
            "i'm not sure", "i am unsure"
        }
        force_web_patterns = [
            r"\bcannot perform (live )?web searches\b",
            r"\bi cannot perform web searches\b",
            r"\bplease\s+verify\b",
            r"\bverify\s+this information\b",
            r"\bi am unsure\b",
            r"\bi'm unsure\b",
            r"\bi am not sure\b",
        ]

        offline_unknown = (not clean_ans) or (clean_ans.strip().lower() in offline_unknown_markers)
        if not offline_unknown and clean_ans:
            for pat in force_web_patterns:
                if re.search(pat, clean_ans, re.I):
                    offline_unknown = True
                    if DEBUG: print("FORCE_WEB_DUE_TO_OFFLINE_TEXT")
                    break

        if _should_use_web(q) or offline_unknown:
            if DEBUG: print("WEB_MODE_TRIGGERED")
            hits = _web_search(q, max_results=8)
            if hits:
                if _FACT_QUERY_RE.search(q):
                    snippets = []
                    for h in hits[:3]:
                        title = h.get('title') or ''
                        snip  = h.get('snippet') or ''
                        if title and snip:
                            snippets.append(f"{title} — {snip}")
                        else:
                            snippets.append(title or snip)
                    sources = [((h.get("title") or h.get("url") or ""), h.get("url") or "") for h in hits if h.get("url")]
                    return _render_web_answer("\n".join(snippets), sources)
                notes = _build_notes_from_hits(hits)
                summary = _chat_offline_summarize(q, notes, max_new_tokens=320).strip()
                if not summary:
                    h0 = hits[0]
                    summary = h0.get("snippet") or h0.get("title") or "Here are some sources I found."
                sources = [((h.get("title") or h.get("url") or ""), h.get("url") or "") for h in hits if h.get("url")]
                return _render_web_answer(_clean_text(summary), sources)

        if clean_ans and not offline_unknown:
            return clean_ans
        fallback = _chat_offline_singleturn(q, max_new_tokens=240)
        return _clean_text(fallback) or "I don't know."
    except Exception:
        try:
            fallback = _chat_offline_singleturn(q, max_new_tokens=240)
            return _clean_text(fallback) or "I don't know."
        except Exception:
            return "I don't know."

# ----------------------------
# Shared cleaners
# ----------------------------
_scrub_meta = getattr(_LLM, "_strip_meta_markers", None) if _LLM else None
_scrub_pers = getattr(_LLM, "_scrub_persona_tokens", None) if _LLM else None
_strip_trans = getattr(_LLM, "_strip_transport_tags", None) if _LLM else None

def _clean_text(s: str) -> str:
    if not s:
        return s
    out = s.replace("\r", "").strip()
    if _strip_trans:
        out = _strip_trans(out)
    if _scrub_pers:
        out = _scrub_pers(out)
    if _scrub_meta:
        out = _scrub_meta(out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()

if __name__ == "__main__":
    import sys
    ask = " ".join(sys.argv[1:]).strip() or "When was the last Robin Hood movie released? Google it"
    print(handle_message("cli", ask))