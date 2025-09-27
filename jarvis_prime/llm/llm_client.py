#!/usr/bin/env python3
# /app/llm_client.py
#
# Jarvis Prime — LLM client (EnviroGuard-first, hard caps, Phi-family chat format, Lexi fallback riffs)
#
# Public entry points:
#   ensure_loaded(...)
#   rewrite(...)
#   riff(...)         → routes to persona_riff()
#   persona_riff(...)

from __future__ import annotations
import os
import sys
import json
import time
import math
import hashlib
import socket
import urllib.request
import urllib.error
import http.client
import re
import threading
import signal
from typing import Optional, Dict, Any, Tuple, List, Union
from collections import deque
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path

# ---- RAG (optional) ----
try:
    from rag import inject_context  # /app/rag.py
except Exception:
    def inject_context(user_msg: str, top_k: int = 5) -> str:
        return "(RAG unavailable)"
# ------------------------

# ============================
# Configuration & Constants
# ============================
@dataclass
class ModelConfig:
    """Model configuration container"""
    url: str = ""
    path: str = ""
    sha256: str = ""
    enabled: bool = False

@dataclass
class ProfileConfig:
    """Profile configuration container"""
    name: str
    cpu_percent: int
    ctx_tokens: int
    timeout_seconds: int

DEFAULT_PROFILES = {
    "manual": ProfileConfig("manual", 100, 8192, 45),
    "hot": ProfileConfig("hot", 90, 6144, 35),
    "normal": ProfileConfig("normal", 80, 4096, 25),
    "boost": ProfileConfig("boost", 70, 2048, 15)
}

# ============================
# Globals
# ============================
LLM_MODE = "none"        # "none" | "llama" | "ollama"
LLM = None               # llama_cpp.Llama instance if LLM_MODE == "llama"
LOADED_MODEL_PATH = None
OLLAMA_URL = ""          # base url if using ollama (e.g., http://127.0.0.1:11434)
DEFAULT_CTX = 4096
OPTIONS_PATH = "/data/options.json"
SYSTEM_PROMPT_PATH = "/app/system_prompt.txt"

# Model metadata (for auto grammar & stops)
_MODEL_ARCH = ""
_CHAT_TEMPLATE = ""
_MODEL_NAME_HINT = ""

# Global reentrant lock so multiple incoming messages don't collide
_GEN_LOCK = threading.RLock()

# ============================
# Logging
# ============================
def _log(msg: str) -> None:
    """Centralized logging with consistent format"""
    print(f"[llm] {msg}", flush=True)

# ============================
# Threading & Context Management
# ============================
def _lock_timeout() -> int:
    """Get lock timeout from environment with bounds checking"""
    try:
        value = int(os.getenv("LLM_LOCK_TIMEOUT_SECONDS", "300").strip())
        return max(1, min(300, value))
    except (ValueError, AttributeError):
        return 10

@contextmanager
def _generation_lock(timeout: Optional[int] = None):
    """Context manager for generation lock with timeout"""
    timeout_val = max(1, int(timeout or _lock_timeout()))
    acquired = False
    end_time = time.time() + timeout_val
    
    try:
        while time.time() < end_time:
            if _GEN_LOCK.acquire(blocking=False):
                acquired = True
                yield True
                return
            time.sleep(0.01)
        yield False
    finally:
        if acquired:
            try:
                _GEN_LOCK.release()
            except Exception as e:
                _log(f"Lock release error: {e}")

# ============================
# Configuration Management
# ============================
class ConfigManager:
    """Centralized configuration management"""
    
    @staticmethod
    def read_options() -> Dict[str, Any]:
        """Read options with error handling and caching"""
        try:
            with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            _log(f"Options file not found: {OPTIONS_PATH}")
            return {}
        except json.JSONDecodeError as e:
            _log(f"Options JSON decode error: {e}")
            return {}
        except Exception as e:
            _log(f"Options read failed: {e}")
            return {}
    
    @staticmethod
    def get_int_option(opts: Dict[str, Any], key: str, default: int, min_val: int = None, max_val: int = None) -> int:
        """Get integer option with bounds checking"""
        try:
            value = int(opts.get(key, default))
            if min_val is not None:
                value = max(min_val, value)
            if max_val is not None:
                value = min(max_val, value)
            return value
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def get_bool_option(opts: Dict[str, Any], key: str, default: bool) -> bool:
        """Get boolean option with type checking"""
        value = opts.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)

# ============================
# System prompt loader
# ============================
def _load_system_prompt() -> str:
    """Load system prompt with better error handling"""
    try:
        path = Path(SYSTEM_PROMPT_PATH)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        _log(f"System prompt load failed: {e}")
    return ""

# ============================
# Text Processing Utilities
# ============================
class TextProcessor:
    """Centralized text processing utilities"""
    
    # Regex patterns (compiled once for efficiency)
    PERSONA_TOKENS = ("dude", "chick", "nerd", "rager", "comedian", "jarvis", "ops", "action", "tappit", "neutral")
    PERS_LEAD_SEQ_RX = re.compile(r'^(?:\s*(?:' + "|".join(PERSONA_TOKENS) + r')\.\s*)+', flags=re.I)
    PERS_AFTER_COLON_RX = re.compile(r'(:\s*)(?:(?:' + "|".join(PERSONA_TOKENS) + r')\.\s*)+', flags=re.I)
    PERS_AFTER_BREAK_RX = re.compile(r'([.!?]\s+|[;,\-–—]\s+)(?:(?:' + "|".join(PERSONA_TOKENS) + r')\.\s*)+', flags=re.I)
    
    TRANSPORT_TAG_RX = re.compile(
        r'^\s*(?:\[(?:smtp|proxy|http|https|gotify|webhook|apprise|ntfy|email|mailer|forward|poster)\]\s*)+',
        flags=re.I
    )
    
    META_LINE_RX = re.compile(
        r'^\s*(?:\[/?(?:SYSTEM|INPUT|OUTPUT|INST)\]\s*|<<\s*/?\s*SYS\s*>>\s*|</?s>\s*)$',
        re.I | re.M
    )
    
    @classmethod
    def scrub_persona_tokens(cls, text: str) -> str:
        """Remove persona name tokens with iterative cleaning"""
        if not text:
            return text
        
        prev = None
        current = text
        
        # Iterate until stable to handle chains
        while prev != current:
            prev = current
            current = cls.PERS_LEAD_SEQ_RX.sub("", current).lstrip()
            current = cls.PERS_AFTER_COLON_RX.sub(r"\1", current)
            current = cls.PERS_AFTER_BREAK_RX.sub(r"\1", current)
        
        return re.sub(r"\s{2,}", " ", current).strip()
    
    @classmethod
    def strip_transport_tags(cls, text: str) -> str:
        """Strip transport tags with iterative cleaning"""
        if not text:
            return text
        
        prev = None
        current = text
        
        while prev != current:
            prev = current
            current = cls.TRANSPORT_TAG_RX.sub("", current).lstrip()
        
        # Clean standalone tags on their own lines
        current = re.sub(
            r'^\s*\[(?:smtp|proxy|http|https|gotify|webhook|apprise|ntfy|email|mailer|forward|poster)\]\s*$',
            '', current, flags=re.I | re.M
        )
        
        return current
    
    @classmethod
    def extract_subject_from_context(cls, context: str) -> str:
        """Extract and clean subject from context"""
        match = re.search(r"Subject:\s*(.+)", context, flags=re.I)
        subject = (match.group(1) if match else context or "").strip()
        subject = cls.strip_transport_tags(subject)
        return re.sub(r"\s+", " ", subject)[:140]
    
    @classmethod
    def sanitize_context_subject(cls, context: str) -> str:
        """Clean subject line within context"""
        if not context:
            return context
        
        match = re.search(r"(Subject:\s*)(.+)", context, flags=re.I)
        if not match:
            return context
        
        prefix, raw_subject = match.group(1), match.group(2)
        cleaned_subject = cls.strip_transport_tags(cls.scrub_persona_tokens(raw_subject))
        
        return context[:match.start(1)] + prefix + cleaned_subject + context[match.end(2):]
    
    @classmethod
    def strip_meta_markers(cls, text: str) -> str:
        """Strip leaked meta tags and system markers"""
        if not text:
            return text
        
        # Remove meta line markers
        result = cls.META_LINE_RX.sub("", text)
        
        # Remove inline meta markers
        result = re.sub(r'\[/?(?:SYSTEM|INPUT|OUTPUT|INST)\]', '', result, flags=re.I)
        result = re.sub(r'<<\s*/?\s*SYS\s*>>', '', result, flags=re.I)
        result = result.replace("<s>", "").replace("</s>", "")
        
        # Remove leaked rewriter instructions
        patterns = [
            r'^\s*you\s+are\s+(?:a|the)?\s*rewriter\.?\s*$',
            r'^\s*message you are a neutral, terse rewriter.*$',
            r'^\s*rewrite neutrally:.*$',
            r'(?mi)^[^\w\n]*message\b.*\byou\s+are\b.*\bneutral\b.*\bterse\b.*\brewriter\b.*$',
            r'you\s+are\s+a?\s*neutral.*?terse\s*rewriter\.?',
            r'message\s+you\s+are\s+a?\s*neutral.*?terse\s*rewriter\.?',
            r'rewrite\s+neutrally\s*:.*'
        ]
        
        for pattern in patterns:
            result = re.sub(pattern, '', result, flags=re.I | re.M)
        
        # Clean up formatting
        result = result.strip().strip('`').strip('"').strip("'").strip()
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        return result
    
    @classmethod
    def trim_lines(cls, text: str, max_lines: int) -> str:
        """Trim text to maximum number of lines"""
        if not max_lines:
            return text
        
        lines = (text or "").splitlines()
        if len(lines) > max_lines:
            keep = lines[:max_lines]
            if keep:
                keep[-1] = keep[-1].rstrip() + " …"
            return "\n".join(keep)
        
        return text
    
    @classmethod
    def soft_trim_chars(cls, text: str, max_chars: int) -> str:
        """Trim text to maximum characters with ellipsis"""
        if not max_chars or len(text) <= max_chars:
            return text
        
        return text[:max(0, max_chars - 1)].rstrip() + "…"
    
    @classmethod
    def trim_to_sentence(cls, text: str, max_chars: int = 140) -> str:
        """Trim to sentence boundary within character limit"""
        if not text:
            return text
        
        text = text.strip()
        if len(text) <= max_chars:
            cut = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
            return text[:cut+1] if cut != -1 else text
        
        truncated = text[:max_chars].rstrip()
        cut = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        
        if cut >= 40:  # Avoid cutting too early
            return truncated[:cut+1]
        
        return truncated

# ============================
# Profile resolution (EnviroGuard-first)
# ============================
class ProfileManager:
    """Manages power profiles with EnviroGuard priority"""
    
    @staticmethod
    def resolve_current_profile() -> ProfileConfig:
        """Resolve active profile with EnviroGuard precedence"""
        config_manager = ConfigManager()
        opts = config_manager.read_options()
        
        profile_name = (
            opts.get("llm_power_profile") or 
            opts.get("power_profile") or 
            os.getenv("LLM_POWER_PROFILE") or 
            "normal"
        ).strip().lower()
        
        try:
            available_keys = sorted(list(opts.keys())[:12])
            if len(opts.keys()) > 12:
                available_keys.append("...")
            _log(f"Available option keys: {available_keys}")
        except Exception:
            pass
        
        profiles = {}
        source = ""
        enviroguard_active = False
        
        # 1) EnviroGuard takes precedence
        eg_profiles = opts.get("llm_enviroguard_profiles")
        if isinstance(eg_profiles, str) and eg_profiles.strip():
            try:
                eg_dict = json.loads(eg_profiles)
                if isinstance(eg_dict, dict) and eg_dict:
                    for key, value in eg_dict.items():
                        if isinstance(value, dict):
                            profiles[key.strip().lower()] = value
                    if profiles:
                        source = "enviroguard(string)"
                        enviroguard_active = True
            except json.JSONDecodeError as e:
                _log(f"EnviroGuard profiles parse error: {e}")
        elif isinstance(eg_profiles, dict) and eg_profiles:
            for key, value in eg_profiles.items():
                if isinstance(value, dict):
                    profiles[key.strip().lower()] = value
            if profiles:
                source = "enviroguard(dict)"
                enviroguard_active = True
        
        # 2) Flat/nested profiles if EnviroGuard not present
        if not profiles:
            # Check flat profiles
            for key in ("manual", "hot", "normal", "boost"):
                value = opts.get(key)
                if isinstance(value, dict):
                    profiles[key] = value
            
            # Check nested profiles
            nested = opts.get("llm_profiles") or opts.get("profiles")
            if isinstance(nested, dict):
                for key, value in nested.items():
                    if isinstance(value, dict):
                        profiles[key.strip().lower()] = value
            
            if profiles:
                source = "flat/nested"
        
        # 3) Global knobs fallback
        if not profiles:
            cpu = opts.get("llm_max_cpu_percent")
            ctx = opts.get("llm_ctx_tokens")
            timeout = opts.get("llm_timeout_seconds")
            
            if any(x is not None for x in (cpu, ctx, timeout)):
                profiles[profile_name] = {
                    "cpu_percent": config_manager.get_int_option({}, "cpu_percent", int(cpu) if cpu else 80, 1, 100),
                    "ctx_tokens": config_manager.get_int_option({}, "ctx_tokens", int(ctx) if ctx else 4096, 512, 32768),
                    "timeout_seconds": config_manager.get_int_option({}, "timeout_seconds", int(timeout) if timeout else 25, 1, 300),
                }
                source = "global_knobs"
        
        # Get profile data
        profile_data = (
            profiles.get(profile_name) or
            profiles.get("normal") or
            (next(iter(profiles.values()), {}) if profiles else {})
        )
        
        if not profile_data:
            _log("Profile resolution: No profiles found, using hard defaults")
            profile_data = {"cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 25}
        
        # Create profile config
        result = ProfileConfig(
            name=profile_name,
            cpu_percent=config_manager.get_int_option(profile_data, "cpu_percent", 80, 1, 100),
            ctx_tokens=config_manager.get_int_option(profile_data, "ctx_tokens", 4096, 512, 32768),
            timeout_seconds=config_manager.get_int_option(profile_data, "timeout_seconds", 25, 1, 300)
        )
        
        _log(f"EnviroGuard active: {enviroguard_active}")
        _log(f"Profile: source={source or 'defaults'} active='{result.name}' "
             f"cpu_percent={result.cpu_percent} ctx_tokens={result.ctx_tokens} "
             f"timeout_seconds={result.timeout_seconds}")
        
        return result

# ============================
# CPU / Threads / Affinity
# ============================
class CPUManager:
    """Manages CPU resources and threading"""
    
    @staticmethod
    def parse_cpuset_list(cpuset_str: str) -> int:
        """Parse CPU set string and return count"""
        total = 0
        for part in (cpuset_str or "").split(","):
            part = part.strip()
            if not part:
                continue
            
            if "-" in part:
                try:
                    start, end = part.split("-", 1)
                    total += int(end) - int(start) + 1
                except (ValueError, IndexError):
                    pass
            else:
                try:
                    int(part)
                    total += 1
                except ValueError:
                    pass
        
        return max(0, total)
    
    @staticmethod
    def get_available_cpus() -> int:
        """Get available CPU count with cgroup/affinity awareness"""
        # Try scheduler affinity first
        try:
            if hasattr(os, "sched_getaffinity"):
                return max(1, len(os.sched_getaffinity(0)))
        except (OSError, AttributeError):
            pass
        
        # Try cgroup v2
        try:
            with open("/sys/fs/cgroup/cpu.max", "r", encoding="utf-8") as f:
                quota_str, period_str = f.read().strip().split()
                if quota_str != "max":
                    quota, period = int(quota_str), int(period_str)
                    if quota > 0 and period > 0:
                        return max(1, quota // period)
        except (FileNotFoundError, ValueError, IndexError):
            pass
        
        # Try cgroup v1
        try:
            with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "r", encoding="utf-8") as f:
                quota = int(f.read().strip())
            with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "r", encoding="utf-8") as f:
                period = int(f.read().strip())
            if quota > 0 and period > 0:
                return max(1, quota // period)
        except (FileNotFoundError, ValueError):
            pass
        
        # Try cpuset
        for path in ("/sys/fs/cgroup/cpuset.cpus", "/sys/fs/cgroup/cpuset/cpuset.cpus"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    count = CPUManager.parse_cpuset_list(f.read().strip())
                    if count > 0:
                        return count
            except FileNotFoundError:
                continue
        
        # Fallback to os.cpu_count()
        return max(1, os.cpu_count() or 1)
    
    @staticmethod
    def pin_cpu_affinity(thread_count: int) -> List[int]:
        """Pin process to specific CPUs"""
        if not (hasattr(os, "sched_getaffinity") and hasattr(os, "sched_setaffinity")):
            return []
        
        try:
            current_cpus = sorted(list(os.sched_getaffinity(0)))
            if thread_count >= len(current_cpus):
                _log(f"CPU affinity: keeping existing CPUs {current_cpus}")
                return current_cpus
            
            target_cpus = set(current_cpus[:max(1, thread_count)])
            os.sched_setaffinity(0, target_cpus)
            pinned_cpus = sorted(list(os.sched_getaffinity(0)))
            _log(f"CPU affinity: pinned to CPUs {pinned_cpus}")
            return pinned_cpus
            
        except (OSError, AttributeError) as e:
            _log(f"CPU affinity pin failed (continuing): {e}")
            return []
    
    @staticmethod
    def calculate_thread_count(cpu_limit_percent: int) -> int:
        """Calculate optimal thread count based on CPU limit"""
        available_cores = CPUManager.get_available_cpus()
        config = ConfigManager()
        opts = config.read_options()
        
        # Check if EnviroGuard is active
        eg_profiles = opts.get("llm_enviroguard_profiles")
        eg_enabled = config.get_bool_option(opts, "llm_enviroguard_enabled", True)
        eg_active = False
        
        if eg_enabled:
            try:
                if isinstance(eg_profiles, str) and eg_profiles.strip():
                    eg_active = isinstance(json.loads(eg_profiles), dict)
                elif isinstance(eg_profiles, dict):
                    eg_active = True
            except (json.JSONDecodeError, TypeError):
                eg_active = False
        
        if eg_active:
            # EnviroGuard enforced limits
            cpu_percent = max(1, min(100, cpu_limit_percent))
            thread_count = max(1, min(available_cores, int(math.floor(available_cores * (cpu_percent / 100.0)))))
            _log(f"Threads: EnviroGuard enforced -> {thread_count} "
                 f"(available={available_cores}, limit={cpu_percent}%)")
            return thread_count
        
        # Check for manual thread override
        forced_threads = config.get_int_option(opts, "llm_threads", 0, 0)
        if forced_threads > 0:
            thread_count = max(1, min(available_cores, forced_threads))
            _log(f"Threads: override via llm_threads={forced_threads} -> using {thread_count} "
                 f"(available={available_cores})")
            return thread_count
        
        # Calculate from CPU limit percentage
        cpu_percent = max(1, min(100, cpu_limit_percent))
        thread_count = max(1, min(available_cores, int(math.floor(available_cores * (cpu_percent / 100.0)))))
        _log(f"Threads: derived from limit -> {thread_count} "
             f"(available={available_cores}, limit={cpu_percent}%)")
        return thread_count

# ============================
# HTTP helpers (with HF auth)
# ============================
class HTTPClient:
    """HTTP client with authentication support"""
    
    class AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
        """Custom redirect handler that preserves auth headers"""
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
            if new_req is None:
                return None
            
            # Preserve auth headers on redirect
            auth_header = req.headers.get("Authorization")
            if auth_header:
                new_req.add_unredirected_header("Authorization", auth_header)
            
            cookie_header = req.headers.get("Cookie")
            if cookie_header:
                new_req.add_unredirected_header("Cookie", cookie_header)
            
            return new_req
    
    @classmethod
    def build_opener_with_headers(cls, headers: Dict[str, str]):
        """Build URL opener with custom headers"""
        handlers = [cls.AuthRedirectHandler()]
        opener = urllib.request.build_opener(*handlers)
        opener.addheaders = list(headers.items())
        return opener
    
    @classmethod
    def get(cls, url: str, headers: Dict[str, str], timeout: int = 180) -> bytes:
        """HTTP GET with custom headers and timeout"""
        opener = cls.build_opener_with_headers(headers)
        try:
            with opener.open(url, timeout=timeout) as response:
                return response.read()
        except urllib.error.URLError as e:
            _log(f"HTTP GET failed for {url}: {e}")
            raise
    
    @classmethod
    def post(cls, url: str, data: bytes, headers: Dict[str, str], timeout: int = 60) -> bytes:
        """HTTP POST with custom headers and timeout"""
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        opener = urllib.request.build_opener()
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.URLError as e:
            _log(f"HTTP POST failed for {url}: {e}")
            raise
    
    @classmethod
    def download_file(cls, url: str, dest_path: str, token: Optional[str] = None, 
                     retries: int = 3, backoff: float = 1.5) -> bool:
        """Download file with retry logic and authentication"""
        try:
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        
        headers = {"User-Agent": "JarvisPrime/1.1 (urllib)"}
        if token:
            headers["Authorization"] = f"Bearer {token.strip()}"
        
        for attempt in range(1, retries + 1):
            try:
                _log(f"Downloading: {url} -> {dest_path} (attempt {attempt}/{retries})")
                content = cls.get(url, headers=headers, timeout=180)
                
                Path(dest_path).write_bytes(content)
                _log("Download completed successfully")
                return True
                
            except urllib.error.HTTPError as e:
                _log(f"Download failed: HTTP {e.code} {getattr(e, 'reason', '')}")
                if e.code in (401, 403, 404):  # Don't retry auth/not found errors
                    return False
            except Exception as e:
                _log(f"Download failed: {e}")
            
            if attempt < retries:
                time.sleep(backoff ** attempt)
        
        return False

# Continue with remaining improvements in next message due to length...