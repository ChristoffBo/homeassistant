#!/usr/bin/env python3
# /app/chatbot.py
#
# Jarvis Prime – Chat lane service (chat + optional web fallback)
# - Default: offline LLM chat via llm_client.chat_generate
# - Web mode if "google it" appears in query
# - RAG mode only if query is HA-related
# - Filters: English-only, block junk domains, require keyword overlap
# - Ranking: authority + keyword overlap + recency
# - Fallbacks: summarizer fallback + direct snippet mode

import os, re, json, time, html, requests, traceback
from typing import Dict, List, Tuple, Optional

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
        return _LLM.chat_generate(user_msg, max_new_tokens=max_new_tokens)
    except Exception:
        return ""

def _chat_offline_summarize(user_msg: str, context_block: str, max_new_tokens: int = 256) -> str:
    if not _llm_ready():
        return ""
    try:
        return _LLM.chat_generate(
            f"Question: {user_msg}\n\nContext:\n{context_block}\n\nAnswer briefly:",
            max_new_tokens=max_new_tokens,
        )
    except Exception:
        return ""

# ----------------------------
# Authority signals
# ----------------------------
_AUTHORITY_SITES = {
    "wikipedia.org": 5,
    "britannica.com": 5,
    "espn.com": 4,
    "formula1.com": 4,
    "github.com": 5,
    "stackoverflow.com": 5,
    "imdb.com": 4,
    "rottentomatoes.com": 4,
    "metacritic.com": 4,
}

_DENY_DOMAINS = {
    "baidu.com", "zhihu.com", "quora.com", "reddit.com", "medium.com",
    "pinterest.com", "linkedin.com", "twitter.com", "facebook.com",
    "tiktok.com", "instagram.com"
}

def _domain_of(url: str) -> str:
    try:
        return re.sub(r"^www\.", "", re.findall(r"https?://([^/]+)/?", url)[0])
    except Exception:
        return url

def _is_deny_domain(url: str) -> bool:
    d = _domain_of(url).lower()
    return any(dd in d for dd in _DENY_DOMAINS)

def _is_junk_result(hit: Dict[str,str]) -> bool:
    u = (hit.get("url") or "").lower()
    if not u: return True
    if _is_deny_domain(u): return True
    s = (hit.get("snippet") or "").strip()
    if not s: return True
    if len(s) < 20: return True
    return False

def _rank_hits(query: str, hits: List[Dict[str,str]], vertical: str) -> List[Dict[str,str]]:
    q_terms = set(re.findall(r"\w+", query.lower()))
    out = []
    for h in hits:
        if _is_junk_result(h): continue
        score = 0
        d = _domain_of(h.get("url",""))
        if d in _AUTHORITY_SITES: score += _AUTHORITY_SITES[d]
        snip = (h.get("snippet") or "").lower()
        overlap = len(q_terms & set(re.findall(r"\w+", snip)))
        score += min(overlap, 5)
        h["_score"] = score
        out.append(h)
    return sorted(out, key=lambda x: x.get("_score",0), reverse=True)
# ----------------------------
# Simple search helpers
# ----------------------------
def _search_with_wikipedia(query: str) -> List[Dict[str,str]]:
    try:
        r = requests.get("https://en.wikipedia.org/w/api.php", params={
            "action":"query","list":"search","srsearch":query,"format":"json"
        }, timeout=6)
        data = r.json()
        out=[]
        for it in data.get("query",{}).get("search",[]):
            title = it.get("title","")
            snip  = re.sub(r"<[^>]+>","",it.get("snippet",""))
            out.append({
                "title": title,
                "snippet": snip,
                "url": f"https://en.wikipedia.org/wiki/{title.replace(' ','_')}"
            })
        return out
    except Exception:
        return []

def _search_with_duckduckgo_lib(query: str, max_results: int=8) -> List[Dict[str,str]]:
    try:
        from duckduckgo_search import DDGS
        out=[]
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                out.append({
                    "title": r.get("title",""),
                    "snippet": r.get("body",""),
                    "url": r.get("href","")
                })
        return out
    except Exception:
        return []

# ----------------------------
# Intent detection
# ----------------------------
def _detect_intent(q: str) -> str:
    ql=q.lower()
    if any(k in ql for k in ["film","movie","tv","actor","actress","imdb","rotten","metacritic"]):
        return "entertainment"
    if any(k in ql for k in ["football","soccer","f1","formula","race","team","player"]):
        return "sports"
    if any(k in ql for k in ["code","python","java","error","bug","github","stack"]):
        return "tech"
    return "general"

# ----------------------------
# Google it trigger (strict)
# ----------------------------
def _should_use_web(q: str) -> bool:
    ql = (q or "").lower()
    return "google it" in ql
# ----------------------------
# Query shaping + backoffs
# ----------------------------
def _build_query_by_vertical(q: str, vertical: str) -> str:
    q=q.strip()
    if vertical=="entertainment":
        return f"{q} site:imdb.com OR site:wikipedia.org"
    if vertical=="sports":
        return f"{q} site:espn.com OR site:formula1.com OR site:wikipedia.org"
    if vertical=="tech":
        return f"{q} site:github.com OR site:stackoverflow.com OR site:wikipedia.org"
    return q+" site:wikipedia.org"

def _try_all_backoffs(raw_q: str, shaped_q: str, vertical: str, max_results: int)->List[Dict[str,str]]:
    hits=[]
    hits.extend(_search_with_wikipedia(raw_q))
    if len(hits)>=max_results:
        return hits
    hits.extend(_search_with_duckduckgo_lib(shaped_q,max_results=max_results))
    return hits[:max_results]

# ----------------------------
# Web search orchestration
# ----------------------------
def _web_search(query: str, max_results: int=8)->List[Dict[str,str]]:
    vertical=_detect_intent(query)
    shaped=_build_query_by_vertical(query,vertical)
    hits=_try_all_backoffs(query,shaped,vertical,max_results)
    ranked=_rank_hits(query,hits,vertical)
    return ranked[:max_results] if ranked else []

# ----------------------------
# Notes + render
# ----------------------------
def _build_notes_from_hits(hits: List[Dict[str,str]])->str:
    lines=[]
    for h in hits[:10]:
        title=(h.get("title") or "").strip()
        url=(h.get("url") or "").strip()
        snip=(h.get("snippet") or "").strip()
        dom=_domain_of(url)
        if title or snip:
            lines.append(f"- [{dom}] {title if title else '(no title)'} :: {snip[:500]} :: {url}")
    return "\n".join(lines) if lines else "- No usable web notes."

def _render_web_answer(summary: str,sources: List[Tuple[str,str]])->str:
    lines=[]
    if summary.strip():
        lines.append(summary.strip())
    if sources:
        dedup,seen=[],set()
        for title,url in sources:
            if not url or url in seen or _is_deny_domain(url): continue
            seen.add(url); dedup.append((title,url))
        if dedup:
            lines.append("\nSources:")
            for title,url in dedup[:5]:
                lines.append(f"• {title.strip() or _domain_of(url)} — {url.strip()}")
    return "\n".join(lines).strip()

# ----------------------------
# Public entry
# ----------------------------
_CACHE: Dict[str,str]={}

def _is_homeassistant_query(q:str)->bool:
    return bool(re.search(r"\b(light|switch|sensor|device|tracker|person|battery|soc|inverter|ha|homeassistant)\b",q,re.I))

def handle_message(source:str,text:str)->str:
    q=(text or "").strip()
    if not q: return ""
    try:
        if q in _CACHE: return _CACHE[q]

        # Google it → force web
        if _should_use_web(q):
            hits=_web_search(q,max_results=8)
            if hits:
                notes=_build_notes_from_hits(hits)
                summary=_chat_offline_summarize(q,notes,max_new_tokens=320).strip()
                if not summary:
                    h0=hits[0]
                    summary=h0.get("snippet") or h0.get("title") or "Here are some sources I found."
                sources=[(h.get("title") or h.get("url") or "",h.get("url") or "") for h in hits if h.get("url")]
                out=_render_web_answer(_clean_text(summary),sources)
                _CACHE[q]=out
                return out

        # RAG for HA queries
        if _is_homeassistant_query(q):
            try:
                from rag import inject_context
                rag_block=inject_context(q,top_k=5)
                if rag_block:
                    ans=_chat_offline_summarize(q,rag_block,max_new_tokens=256)
                    clean_ans=_clean_text(ans)
                    if clean_ans: return clean_ans
            except Exception: pass

        # Offline LLM
        ans=_chat_offline_singleturn(q,max_new_tokens=256)
        clean_ans=_clean_text(ans)
        if not clean_ans or clean_ans.lower() in {"i don't know.","i dont know","unknown","no idea","i'm not sure","i am unsure"}:
            hits=_web_search(q,max_results=8)
            if hits:
                notes=_build_notes_from_hits(hits)
                summary=_chat_offline_summarize(q,notes,max_new_tokens=320).strip()
                if not summary:
                    h0=hits[0]; summary=h0.get("snippet") or h0.get("title") or "Here are some sources I found."
                sources=[(h.get("title") or h.get("url") or "",h.get("url") or "") for h in hits if h.get("url")]
                out=_render_web_answer(_clean_text(summary),sources)
                _CACHE[q]=out
                return out

        if clean_ans:
            _CACHE[q]=clean_ans
            return clean_ans

        return "I don't know."
    except Exception:
        return "I don't know."

# ----------------------------
# Cleaners
# ----------------------------
_scrub_meta=getattr(_LLM,"_strip_meta_markers",None) if _LLM else None
_scrub_pers=getattr(_LLM,"_scrub_persona_tokens",None) if _LLM else None
_strip_trans=getattr(_LLM,"_strip_transport_tags",None) if _LLM else None

def _clean_text(s:str)->str:
    if not s: return s
    out=s.replace("\r","").strip()
    if _strip_trans:
        try: out=_strip_trans(out)
        except Exception: pass
    if _scrub_pers:
        try: out=_scrub_pers(out)
        except Exception: pass
    if _scrub_meta:
        try: out=_scrub_meta(out)
        except Exception: pass
    return re.sub(r"\n{3,}","\n\n",out).strip()

if __name__=="__main__":
    import sys
    ask=" ".join(sys.argv[1:]).strip() or "Who is the current F1 leader google it"
    print(handle_message("cli",ask))