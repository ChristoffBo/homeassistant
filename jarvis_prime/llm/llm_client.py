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
#   persona_riff_ex(...)
#   chat_generate(...)

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
from pathlib import Path
from dataclasses import dataclass
from contextlib import contextmanager
from enum import Enum

# ---- RAG (optional) ----
try:
    from rag import inject_context  # /app/rag.py
except ImportError:
    def inject_context(user_msg: str, top_k: int = 5) -> str:
        return "(RAG unavailable)"

# ============================
# Enums and Data Classes
# ============================

class LLMMode(Enum):
    NONE = "none"
    LLAMA = "llama"
    OLLAMA = "ollama"

@dataclass
class Profile:
    name: str
    cpu_percent: int
    ctx_tokens: int
    timeout_seconds: int

@dataclass
class ModelConfig:
    url: str = ""
    path: str = ""
    sha256: str = ""
    name_hint: str = ""

@dataclass
class GenerationParams:
    max_tokens: int
    timeout: int
    temperature: float = 0.35
    top_p: float = 0.9
    repeat_penalty: float = 1.1

# ============================
# Global State Management
# ============================

class LLMState:
    """Centralized state management for the LLM client"""
    
    def __init__(self):
        self.mode: LLMMode = LLMMode.NONE
        self.llm: Optional[Any] = None
        self.loaded_model_path: Optional[str] = None
        self.ollama_url: str = ""
        self.default_ctx: int = 4096
        self.model_arch: str = ""
        self.chat_template: str = ""
        self.model_name_hint: str = ""
        self._lock = threading.RLock()
    
    def reset(self):
        """Reset all state to initial values"""
        with self._lock:
            self.mode = LLMMode.NONE
            self.llm = None
            self.loaded_model_path = None
            self.ollama_url = ""
            self.model_arch = ""
            self.chat_template = ""
            self.model_name_hint = ""

# Global state instance
_state = LLMState()

# ============================
# Configuration Management
# ============================

class ConfigManager:
    """Manages configuration loading and validation"""
    
    OPTIONS_PATH = "/data/options.json"
    SYSTEM_PROMPT_PATH = "/app/system_prompt.txt"
    
    @classmethod
    def read_options(cls) -> Dict[str, Any]:
        """Read and parse options file with error handling"""
        try:
            with open(cls.OPTIONS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            _log(f"Options file not found: {cls.OPTIONS_PATH}")
            return {}
        except json.JSONDecodeError as e:
            _log(f"Invalid JSON in options file: {e}")
            return {}
        except Exception as e:
            _log(f"Failed to read options ({cls.OPTIONS_PATH}): {e}")
            return {}
    
    @classmethod
    def get_int_opt(cls, opts: Dict[str, Any], key: str, default: int) -> int:
        """Safely extract integer option with validation"""
        try:
            value = opts.get(key, default)
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                return int(value.strip())
            return default
        except (ValueError, TypeError):
            _log(f"Invalid value for option '{key}': {opts.get(key)}, using default: {default}")
            return default
    
    @classmethod
    def get_bool_opt(cls, opts: Dict[str, Any], key: str, default: bool) -> bool:
        """Safely extract boolean option with validation"""
        value = opts.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower().strip() in ("1", "true", "yes", "on")
        if isinstance(value, (int, float)):
            return bool(value)
        return default
    
    @classmethod
    def load_system_prompt(cls) -> str:
        """Load system prompt from file with error handling"""
        try:
            if os.path.exists(cls.SYSTEM_PROMPT_PATH):
                with open(cls.SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
                    return f.read().strip()
        except Exception as e:
            _log(f"System prompt load failed: {e}")
        return ""

# ============================
# Logging
# ============================

def _log(msg: str) -> None:
    """Centralized logging with timestamp"""
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{timestamp}][llm] {msg}", flush=True)

# ============================
# Thread Safety and Resource Management
# ============================

class LockManager:
    """Manages thread locks with timeout support"""
    
    def __init__(self):
        self._lock = threading.RLock()
    
    def _get_timeout(self) -> int:
        """Get lock timeout from environment or use default"""
        try:
            value = int(os.getenv("LLM_LOCK_TIMEOUT_SECONDS", "300").strip())
            return max(1, min(300, value))
        except (ValueError, TypeError):
            return 10
    
    @contextmanager
    def acquire_with_timeout(self, timeout: Optional[int] = None):
        """Context manager for acquiring lock with timeout"""
        effective_timeout = timeout or self._get_timeout()
        end_time = time.time() + effective_timeout
        acquired = False
        
        try:
            while time.time() < end_time:
                if self._lock.acquire(blocking=False):
                    acquired = True
                    yield True
                    return
                time.sleep(0.01)
            yield False
        finally:
            if acquired:
                try:
                    self._lock.release()
                except Exception as e:
                    _log(f"Lock release failed: {e}")

# Global lock manager
_lock_manager = LockManager()

# ============================
# Text Processing Utilities
# ============================

class TextProcessor:
    """Handles text cleaning, processing, and validation"""
    
    # Compiled regex patterns for better performance
    _PERSONA_TOKENS = ("dude", "chick", "nerd", "rager", "comedian", "jarvis", "ops", "action", "tappit", "neutral")
    _PERSONA_PATTERN = "|".join(_PERSONA_TOKENS)
    
    _PERS_LEAD_SEQ_RX = re.compile(rf'^(?:\s*(?:{_PERSONA_PATTERN})\.\s*)+', flags=re.I)
    _PERS_AFTER_COLON_RX = re.compile(rf'(:\s*)(?:(?:{_PERSONA_PATTERN})\.\s*)+', flags=re.I)
    _PERS_AFTER_BREAK_RX = re.compile(rf'([.!?]\s+|[;,\-–—]\s+)(?:(?:{_PERSONA_PATTERN})\.\s*)+', flags=re.I)
    
    _TRANSPORT_TAG_RX = re.compile(
        r'^\s*(?:\[(?:smtp|proxy|http|https|gotify|webhook|apprise|ntfy|email|mailer|forward|poster)\]\s*)+',
        flags=re.I
    )
    
    _META_LINE_RX = re.compile(
        r'^\s*(?:\[/?(?:SYSTEM|INPUT|OUTPUT|INST)\]\s*|<<\s*/?\s*SYS\s*>>\s*|</?s>\s*)$',
        re.I | re.M
    )
    
    @classmethod
    def scrub_persona_tokens(cls, text: str) -> str:
        """Remove persona name tokens from text"""
        if not text:
            return text
        
        prev, current = None, text
        max_iterations = 10  # Prevent infinite loops
        iteration = 0
        
        while prev != current and iteration < max_iterations:
            prev = current
            current = cls._PERS_LEAD_SEQ_RX.sub("", current).lstrip()
            current = cls._PERS_AFTER_COLON_RX.sub(r"\1", current)
            current = cls._PERS_AFTER_BREAK_RX.sub(r"\1", current)
            iteration += 1
        
        return re.sub(r"\s{2,}", " ", current).strip()
    
    @classmethod
    def strip_transport_tags(cls, text: str) -> str:
        """Remove transport protocol tags from text"""
        if not text:
            return text
        
        prev, current = None, text
        max_iterations = 5
        iteration = 0
        
        while prev != current and iteration < max_iterations:
            prev = current
            current = cls._TRANSPORT_TAG_RX.sub("", current).lstrip()
            iteration += 1
        
        # Clean up remaining transport tags
        current = re.sub(
            r'^\s*\[(?:smtp|proxy|http|https|gotify|webhook|apprise|ntfy|email|mailer|forward|poster)\]\s*$',
            '', current, flags=re.I | re.M
        )
        return current
    
    @classmethod
    def extract_subject_from_context(cls, context: str) -> str:
        """Extract and clean subject line from context"""
        match = re.search(r"Subject:\s*(.+)", context, flags=re.I)
        subject = (match.group(1) if match else context or "").strip()
        subject = cls.strip_transport_tags(subject)
        return re.sub(r"\s+", " ", subject)[:140]
    
    @classmethod
    def sanitize_context_subject(cls, context: str) -> str:
        """Clean persona tokens and transport tags from subject in context"""
        if not context:
            return context
        
        match = re.search(r"(Subject:\s*)(.+)", context, flags=re.I)
        if not match:
            return context
        
        prefix, raw_subject = match.group(1), match.group(2)
        cleaned = cls.strip_transport_tags(cls.scrub_persona_tokens(raw_subject))
        return context[:match.start(1)] + prefix + cleaned + context[match.end(2):]
    
    @classmethod
    def strip_meta_markers(cls, text: str) -> str:
        """Remove leaked meta tags and system markers"""
        if not text:
            return text
        
        # Remove meta line markers
        output = cls._META_LINE_RX.sub("", text)
        
        # Remove inline meta markers
        patterns = [
            (r'(?:\[/?(?:SYSTEM|INPUT|OUTPUT|INST)\])', ''),
            (r'<<\s*/?\s*SYS\s*>>', ''),
            (r'</?s>', ''),
            (r'^\s*you\s+are\s+(?:a|the)?\s*rewriter\.?\s*$', ''),
            (r'^\s*message you are a neutral, terse rewriter.*$', ''),
            (r'^\s*rewrite neutrally:.*$', ''),
            (r'(?mi)^[^\w\n]*message\b.*\byou\s+are\b.*\bneutral\b.*\bterse\b.*\brewriter\b.*$', ''),
            (r'you\s+are\s+a?\s*neutral.*?terse\s*rewriter\.?', ''),
            (r'message\s+you\s+are\s+a?\s*neutral.*?terse\s*rewriter\.?', ''),
            (r'rewrite\s+neutrally\s*:.*', ''),
        ]
        
        for pattern, replacement in patterns:
            output = re.sub(pattern, replacement, output, flags=re.I | re.M)
        
        # Clean up formatting
        output = output.strip().strip('`').strip('"').strip("'").strip()
        output = re.sub(r'\n{3,}', '\n\n', output)
        
        return output
    
    @classmethod
    def trim_lines(cls, text: str, max_lines: int) -> str:
        """Trim text to maximum number of lines"""
        if not max_lines:
            return text
        
        lines = text.splitlines()
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
        """Trim text to sentence boundary within character limit"""
        if not text:
            return text
        
        text = text.strip()
        if len(text) <= max_chars:
            cut_pos = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
            return text[:cut_pos + 1] if cut_pos != -1 else text
        
        truncated = text[:max_chars].rstrip()
        cut_pos = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        
        if cut_pos >= 40:  # Avoid cutting too early
            return truncated[:cut_pos + 1]
        return truncated

# ============================
# CPU and Resource Management
# ============================

class ResourceManager:
    """Manages CPU affinity, thread limits, and system resources"""
    
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
                except ValueError:
                    pass
            else:
                try:
                    int(part)
                    total += 1
                except ValueError:
                    pass
        return max(0, total)
    
    @classmethod
    def get_available_cpus(cls) -> int:
        """Get available CPU count considering cgroups and affinity"""
        # Try scheduler affinity first
        try:
            if hasattr(os, "sched_getaffinity"):
                return max(1, len(os.sched_getaffinity(0)))
        except Exception:
            pass
        
        # Try cgroup v2
        try:
            with open("/sys/fs/cgroup/cpu.max", "r", encoding="utf-8") as f:
                quota, period = f.read().strip().split()
                if quota != "max":
                    q, p = int(quota), int(period)
                    if q > 0 and p > 0:
                        return max(1, q // p)
        except Exception:
            pass
        
        # Try cgroup v1
        try:
            with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "r", encoding="utf-8") as f:
                quota = int(f.read().strip())
            with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "r", encoding="utf-8") as f:
                period = int(f.read().strip())
            if quota > 0 and period > 0:
                return max(1, quota // period)
        except Exception:
            pass
        
        # Try cpuset
        for path in ("/sys/fs/cgroup/cpuset.cpus", "/sys/fs/cgroup/cpuset/cpuset.cpus"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    count = cls.parse_cpuset_list(f.read().strip())
                    if count > 0:
                        return count
            except Exception:
                pass
        
        # Fallback to system CPU count
        return max(1, os.cpu_count() or 1)
    
    @staticmethod
    def pin_cpu_affinity(target_cpus: int) -> List[int]:
        """Pin process to specific number of CPUs"""
        if not hasattr(os, "sched_getaffinity") or not hasattr(os, "sched_setaffinity"):
            return []
        
        try:
            current_cpus = sorted(list(os.sched_getaffinity(0)))
            if target_cpus >= len(current_cpus):
                _log(f"Affinity: keeping existing CPUs {current_cpus}")
                return current_cpus
            
            target_set = set(current_cpus[:max(1, target_cpus)])
            os.sched_setaffinity(0, target_set)
            pinned_cpus = sorted(list(os.sched_getaffinity(0)))
            _log(f"Affinity: pinned to CPUs {pinned_cpus}")
            return pinned_cpus
        except Exception as e:
            _log(f"Affinity pin failed (continuing): {e}")
            return []
    
    @classmethod
    def calculate_thread_count(cls, cpu_limit_percent: int, options: Dict[str, Any]) -> int:
        """Calculate optimal thread count based on CPU limits and EnviroGuard settings"""
        available_cpus = cls.get_available_cpus()
        
        # Check EnviroGuard enforcement
        eg_profiles = options.get("llm_enviroguard_profiles")
        eg_enabled = ConfigManager.get_bool_opt(options, "llm_enviroguard_enabled", True)
        eg_active = False
        
        if eg_enabled and eg_profiles:
            try:
                if isinstance(eg_profiles, str) and eg_profiles.strip():
                    eg_active = isinstance(json.loads(eg_profiles), dict)
                elif isinstance(eg_profiles, dict):
                    eg_active = True
            except Exception:
                pass
        
        if eg_active:
            try:
                percent = max(1, min(100, int(cpu_limit_percent or 100)))
            except (ValueError, TypeError):
                percent = 100
            
            thread_count = max(1, min(available_cpus, int(math.floor(available_cpus * (percent / 100.0)))))
            _log(f"Threads: EnviroGuard enforced -> {thread_count} (available={available_cpus}, limit={percent}%)")
            return thread_count
        
        # Check for manual thread override
        forced_threads = ConfigManager.get_int_opt(options, "llm_threads", 0)
        if forced_threads > 0:
            thread_count = max(1, min(available_cpus, forced_threads))
            _log(f"Threads: override via llm_threads={forced_threads} -> using {thread_count} (available={available_cpus})")
            return thread_count
        
        # Calculate from percentage
        try:
            percent = max(1, min(100, int(cpu_limit_percent or 100)))
        except (ValueError, TypeError):
            percent = 100
        
        thread_count = max(1, min(available_cpus, int(math.floor(available_cpus * (percent / 100.0)))))
        _log(f"Threads: derived from limit -> {thread_count} (available={available_cpus}, limit={percent}%)")
        return thread_count

# ============================
# Profile Management (EnviroGuard-first)
# ============================

class ProfileManager:
    """Manages power profiles with EnviroGuard priority"""
    
    @staticmethod
    def resolve_current_profile() -> Profile:
        """Resolve active profile with EnviroGuard-first precedence"""
        options = ConfigManager.read_options()
        profile_name = (
            options.get("llm_power_profile") or
            options.get("power_profile") or
            os.getenv("LLM_POWER_PROFILE") or
            "normal"
        ).strip().lower()
        
        try:
            keys_preview = sorted(list(options.keys()))[:12]
            preview_text = f"{keys_preview}{' ...' if len(options.keys()) > 12 else ''}"
            _log(f"Options keys: {preview_text}")
        except Exception:
            pass
        
        profiles: Dict[str, Dict[str, Any]] = {}
        source = ""
        enviroguard_active = False
        
        # 1) EnviroGuard profiles (highest priority)
        eg_profiles = options.get("llm_enviroguard_profiles")
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
        
        # 2) Flat/nested profiles (only if EnviroGuard not present)
        if not profiles:
            # Check flat profile definitions
            for profile_key in ("manual", "hot", "normal", "boost"):
                value = options.get(profile_key)
                if isinstance(value, dict):
                    profiles[profile_key] = value
            
            # Check nested profile definitions
            nested = options.get("llm_profiles") or options.get("profiles")
            if isinstance(nested, dict):
                for key, value in nested.items():
                    if isinstance(value, dict):
                        profiles[key.strip().lower()] = value
            
            if profiles and not source:
                source = "flat/nested"
        
        # 3) Global knobs fallback
        if not profiles:
            cpu = options.get("llm_max_cpu_percent")
            ctx = options.get("llm_ctx_tokens")
            timeout = options.get("llm_timeout_seconds")
            
            if cpu is not None or ctx is not None or timeout is not None:
                def safe_int(value, default):
                    try:
                        return int(str(value).strip())
                    except (ValueError, TypeError):
                        return default
                
                profiles[profile_name] = {
                    "cpu_percent": safe_int(cpu, 80),
                    "ctx_tokens": safe_int(ctx, 4096),
                    "timeout_seconds": safe_int(timeout, 25),
                }
                source = "global_knobs"
        
        # Get profile data with fallbacks
        profile_data = (
            profiles.get(profile_name) or
            profiles.get("normal") or
            (next(iter(profiles.values()), {}) if profiles else {})
        )
        
        if not profile_data:
            _log("Profile resolution: NO profiles found -> using hard defaults (80/4096/25)")
        
        cpu_percent = int(profile_data.get("cpu_percent", 80))
        ctx_tokens = int(profile_data.get("ctx_tokens", 4096))
        timeout_seconds = int(profile_data.get("timeout_seconds", 25))
        
        _log(f"EnviroGuard active: {enviroguard_active}")
        _log(f"Profile: src={source or 'defaults'} active='{profile_name}' "
             f"cpu_percent={cpu_percent} ctx_tokens={ctx_tokens} timeout_seconds={timeout_seconds}")
        
        return Profile(
            name=profile_name,
            cpu_percent=cpu_percent,
            ctx_tokens=ctx_tokens,
            timeout_seconds=timeout_seconds
        )

# ============================
# HTTP Client with Authentication
# ============================

class HTTPClient:
    """HTTP client with authentication and retry support"""
    
    class AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
        """Preserve auth headers during redirects"""
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
            if new_req is None:
                return None
            
            # Preserve authorization and cookies
            auth = req.headers.get("Authorization")
            if auth:
                new_req.add_unredirected_header("Authorization", auth)
            
            cookie = req.headers.get("Cookie")
            if cookie:
                new_req.add_unredirected_header("Cookie", cookie)
            
            return new_req
    
    @classmethod
    def build_opener(cls, headers: Dict[str, str]):
        """Build URL opener with custom headers"""
        handlers = [cls.AuthRedirectHandler()]
        opener = urllib.request.build_opener(*handlers)
        opener.addheaders = list(headers.items())
        return opener
    
    @classmethod
    def get(cls, url: str, headers: Dict[str, str], timeout: int = 180) -> bytes:
        """Perform HTTP GET request"""
        opener = cls.build_opener(headers)
        with opener.open(url, timeout=timeout) as response:
            return response.read()
    
    @classmethod
    def post(cls, url: str, data: bytes, headers: Dict[str, str], timeout: int = 60) -> bytes:
        """Perform HTTP POST request"""
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        opener = urllib.request.build_opener()
        with opener.open(request, timeout=timeout) as response:
            return response.read()
    
    @classmethod
    def download_file(cls, url: str, destination: str, token: Optional[str] = None, 
                     retries: int = 3, backoff: float = 1.5) -> bool:
        """Download file with retry logic and authentication"""
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
        except Exception:
            pass
        
        headers = {"User-Agent": "JarvisPrime/1.1 (urllib)"}
        if token:
            headers["Authorization"] = f"Bearer {token.strip()}"
        
        for attempt in range(1, retries + 1):
            try:
                _log(f"Downloading: {url} -> {destination} (attempt {attempt}/{retries})")
                content = cls.get(url, headers=headers, timeout=180)
                
                with open(destination, "wb") as f:
                    f.write(content)
                
                _log("Download completed successfully")
                return True
                
            except urllib.error.HTTPError as e:
                _log(f"Download failed: HTTP {e.code} {getattr(e, 'reason', '')}")
                if e.code in (401, 403, 404):
                    return False
            except Exception as e:
                _log(f"Download failed: {e}")
            
            if attempt < retries:
                sleep_time = backoff ** attempt
                _log(f"Retrying in {sleep_time:.1f} seconds...")
                time.sleep(sleep_time)
        
        return False

# ============================
# Model Management
# ============================

class ModelManager:
    """Handles model downloading, validation, and metadata"""
    
    @staticmethod
    def coerce_model_path(model_url: str, model_path: str) -> str:
        """Ensure model path is properly formatted"""
        if not model_path or model_path.endswith("/"):
            filename = model_url.split("/")[-1] if model_url else "model.gguf"
            base_dir = model_path or "/share/jarvis_prime/models"
            return os.path.join(base_dir, filename)
        return model_path
    
    @classmethod
    def ensure_local_model(cls, model_url: str, model_path: str, 
                          token: Optional[str], sha256: str) -> Optional[str]:
        """Ensure model is available locally, downloading if necessary"""
        path = cls.coerce_model_path(model_url, model_path)
        
        # Download if not present
        if not os.path.exists(path):
            if not model_url:
                _log("No model file on disk and no model_url to download")
                return None
            
            if not HTTPClient.download_file(model_url, path, token):
                return None
        
        # Validate SHA256 if provided
        if sha256:
            try:
                hash_obj = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        hash_obj.update(chunk)
                
                calculated_hash = hash_obj.hexdigest()
                if calculated_hash.lower() != sha256.lower():
                    _log(f"SHA256 mismatch: got={calculated_hash} want={sha256} (refusing to load)")
                    return None
            except Exception as e:
                _log(f"SHA256 check failed (continuing without): {e}")
        
        return path
    
    @staticmethod
    def resolve_from_options(model_url: str, model_path: str, 
                           hf_token: Optional[str]) -> Tuple[str, str, Optional[str]]:
        """Resolve model configuration from options file"""
        url = model_url.strip() if model_url else ""
        path = model_path.strip() if model_path else ""
        token = hf_token.strip() if hf_token else None
        
        if url and path:
            return url, path, token
        
        options = ConfigManager.read_options()
        choice = options.get("llm_choice", "").strip()
        
        if not token:
            token_str = options.get("llm_hf_token", "").strip()
            token = token_str or None
        
        candidates: List[Tuple[str, str]] = []
        
        # Handle custom choice
        if choice.lower() == "custom":
            custom_url = options.get("llm_model_url", "").strip()
            custom_path = options.get("llm_model_path", "").strip()
            candidates.append((custom_url, custom_path))
        elif choice:
            choice_url = options.get(f"llm_{choice}_url", "").strip()
            choice_path = options.get(f"llm_{choice}_path", "").strip()
            candidates.append((choice_url, choice_path))
        
        # Build priority list
        priority_raw = options.get("llm_models_priority", "").strip()
        if priority_raw:
            priority_names = [name.strip().lower() for name in priority_raw.split(",") if name.strip()]
        else:
            priority_names = ["phi35_q5_uncensored", "phi35_q5", "phi35_q4", "phi3"]
        
        # Add models from priority list
        seen = set()
        for name in priority_names + ["phi35_q5_uncensored", "phi35_q5", "phi35_q4", "phi3"]:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            
            if ConfigManager.get_bool_opt(options, f"llm_{key}_enabled", False):
                model_url_key = options.get(f"llm_{key}_url", "").strip()
                model_path_key = options.get(f"llm_{key}_path", "").strip()
                candidates.append((model_url_key, model_path_key))
        
        # Return first valid candidate
        for candidate_url, candidate_path in candidates:
            if candidate_url and candidate_path:
                _log(f"Options resolver -> choice={choice or 'auto'} "
                     f"url={os.path.basename(candidate_url) if candidate_url else ''} "
                     f"path='{os.path.basename(candidate_path)}'")
                return candidate_url, candidate_path, token
        
        return url, path, token

# ============================
# LLM Backend Implementations
# ============================

class LlamaBackend:
    """llama-cpp-python backend implementation"""
    
    @staticmethod
    def try_import():
        """Attempt to import llama-cpp-python"""
        try:
            import llama_cpp
            return llama_cpp
        except ImportError as e:
            _log(f"llama-cpp not available: {e}")
            return None
    
    @classmethod
    def load_model(cls, model_path: str, ctx_tokens: int, cpu_limit: int, options: Dict[str, Any]) -> bool:
        """Load GGUF model with llama-cpp-python"""
        llama_cpp = cls.try_import()
        if not llama_cpp:
            return False
        
        try:
            thread_count = ResourceManager.calculate_thread_count(cpu_limit, options)
            
            # Set environment variables for thread control
            env_vars = {
                "OMP_NUM_THREADS": str(thread_count),
                "OMP_DYNAMIC": "FALSE",
                "OMP_PROC_BIND": "TRUE",
                "OMP_PLACES": "cores",
                "LLAMA_THREADS": str(thread_count),
                "GGML_NUM_THREADS": str(thread_count),
            }
            
            for key, value in env_vars.items():
                os.environ[key] = value
            
            # Pin CPU affinity
            pinned_cpus = ResourceManager.pin_cpu_affinity(thread_count)
            
            _log(f"Thread environment -> {' '.join(f'{k}={v}' for k, v in env_vars.items())} "
                 f"affinity={'/'.join(map(str, pinned_cpus)) if pinned_cpus else 'unchanged'}")
            
            # Load model
            _state.llm = llama_cpp.Llama(
                model_path=model_path,
                n_ctx=ctx_tokens,
                n_threads=thread_count,
                n_threads_batch=thread_count,
                n_batch=128,
                n_ubatch=128
            )
            
            cls._update_model_metadata()
            _state.loaded_model_path = model_path
            _state.mode = LLMMode.LLAMA
            
            _log(f"Loaded GGUF model: {model_path} (ctx={ctx_tokens}, threads={thread_count})")
            return True
            
        except Exception as e:
            _log(f"Llama load failed: {e}")
            _state.llm = None
            _state.loaded_model_path = None
            _state.mode = LLMMode.NONE
            return False
    
    @classmethod
    def _update_model_metadata(cls):
        """Update global model metadata from loaded model"""
        try:
            metadata = getattr(_state.llm, "metadata", None)
            if callable(metadata):
                metadata = _state.llm.metadata()
            
            if isinstance(metadata, dict):
                _state.model_arch = str(metadata.get("general.architecture", ""))
                _state.chat_template = str(metadata.get("tokenizer.chat_template", ""))
                
                if _state.chat_template:
                    _log(f"Using GGUF chat template: {_state.chat_template[:120]}...")
        except Exception as e:
            _log(f"Failed to update model metadata: {e}")
    
    @staticmethod
    def generate(prompt: str, params: GenerationParams, stops: List[str], 
                with_grammar: bool = False) -> str:
        """Generate text using llama-cpp-python"""
        try:
            # Set up timeout handler
            def timeout_handler(signum, frame):
                raise TimeoutError("Generation timeout")
            
            if hasattr(signal, "SIGALRM"):
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(max(1, params.timeout))
            
            # Prepare generation parameters
            gen_params = {
                "prompt": prompt,
                "max_tokens": max(1, params.max_tokens),
                "temperature": params.temperature,
                "top_p": params.top_p,
                "repeat_penalty": params.repeat_penalty,
                "stop": stops,
            }
            
            # Add grammar if requested
            if with_grammar:
                gen_params = cls._maybe_add_grammar(gen_params)
            
            start_time = time.time()
            result = _state.llm(**gen_params)
            ttft = time.time() - start_time
            _log(f"TTFT ~ {ttft:.2f}s")
            
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)
            
            text = (result.get("choices", [{}])[0].get("text", ""))
            return text.strip() if text else ""
            
        except TimeoutError as e:
            _log(f"Llama generation timeout: {e}")
            return ""
        except Exception as e:
            _log(f"Llama generation error: {e}")
            return ""
        finally:
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)
    
    @staticmethod
    def _maybe_add_grammar(params: dict) -> dict:
        """Add grammar to generation parameters if supported"""
        try:
            import llama_cpp
            if hasattr(llama_cpp, "LlamaGrammar"):
                # Simple grammar for riffs (≤3 lines, ≤140 chars each)
                riff_grammar = r"""
root  ::= line ( "\n" line ){0,2}
line  ::= char{1,140}
char  ::= [\x20-\x7E]
"""
                params["grammar"] = llama_cpp.LlamaGrammar.from_string(riff_grammar)
            else:
                _log("Grammar: LlamaGrammar not available; skipping")
        except Exception as e:
            _log(f"Grammar setup failed; skipping: {e}")
        
        return params

class OllamaBackend:
    """Ollama HTTP API backend implementation"""
    
    @staticmethod
    def check_availability(base_url: str, timeout: int = 2) -> bool:
        """Check if Ollama service is available"""
        try:
            parsed_url = base_url
            if base_url.startswith("http://"):
                parsed_url = base_url[7:]
            elif base_url.startswith("https://"):
                parsed_url = base_url[8:]
            
            host_port = parsed_url.strip("/").split("/")[0]
            if ":" in host_port:
                host, port_str = host_port.split(":", 1)
                port = int(port_str)
            else:
                host, port = host_port, 80
            
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False
    
    @staticmethod
    def generate(base_url: str, model_name: str, prompt: str, params: GenerationParams, 
                stops: Optional[List[str]] = None) -> str:
        """Generate text using Ollama API"""
        try:
            url = base_url.rstrip("/") + "/api/generate"
            payload = {
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": params.temperature,
                    "top_p": params.top_p,
                    "repeat_penalty": params.repeat_penalty
                }
            }
            
            if params.max_tokens > 0:
                payload["options"]["num_predict"] = params.max_tokens
            
            if stops:
                payload["stop"] = stops
            
            data = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            
            response = HTTPClient.post(url, data=data, headers=headers, timeout=params.timeout)
            result = json.loads(response.decode("utf-8"))
            
            return result.get("response", "") or ""
            
        except urllib.error.HTTPError as e:
            _log(f"Ollama HTTP {e.code}: {getattr(e, 'reason', '')}")
            return ""
        except Exception as e:
            _log(f"Ollama error: {e}")
            return ""
    
    @staticmethod
    def extract_model_name(model_url: str) -> str:
        """Extract model name from URL for Ollama"""
        if not model_url:
            return "llama3"
        
        filename = model_url.strip("/").split("/")[-1]
        if "." in filename:
            filename = filename.split(".")[0]
        
        return filename or "llama3"

# ============================
# Model Detection and Configuration
# ============================

class ModelDetector:
    """Detects model type and provides appropriate configuration"""
    
    @staticmethod
    def is_phi3_family() -> bool:
        """Check if loaded model is from Phi-3 family"""
        combined_info = " ".join([_state.model_arch, _state.chat_template]).lower()
        return ("phi3" in combined_info) or ("<|user|>" in combined_info and 
                                           "<|assistant|>" in combined_info and 
                                           "<|end|>" in combined_info)
    
    @classmethod
    def get_stop_tokens(cls) -> List[str]:
        """Get appropriate stop tokens for loaded model"""
        if cls.is_phi3_family():
            return ["<|end|>", "<|endoftext|>"]
        return ["</s>", "[/INST]"]
    
    @classmethod
    def should_use_grammar_auto(cls) -> bool:
        """Determine if grammar should be used automatically"""
        if cls.is_phi3_family():
            return False
        
        template_lower = (_state.chat_template or "").lower()
        return "INST" in _state.chat_template or "llama" in template_lower

# ============================
# Context and Token Management
# ============================

class ContextManager:
    """Manages context windows and token estimation"""
    
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimation when tokenizer unavailable"""
        return max(1, len(text) // 4)
    
    @classmethod
    def check_overflow(cls, input_tokens: int, max_output: int, 
                      max_context: int, reserve: int = 256) -> bool:
        """Check if generation would overflow context window"""
        budget = max_context - max(64, reserve)
        total_needed = input_tokens + max(0, max_output)
        return total_needed > max(1, budget)
    
    @classmethod
    def get_token_count(cls, text: str) -> int:
        """Get accurate token count if possible, fallback to estimation"""
        try:
            if _state.llm and hasattr(_state.llm, 'tokenize'):
                tokens = _state.llm.tokenize(text.encode("utf-8"), add_bos=True)
                return len(tokens)
        except Exception as e:
            _log(f"Tokenization failed, using estimation: {e}")
        
        return cls.estimate_tokens(text)

# ============================
# Prompt Templates
# ============================

class PromptBuilder:
    """Builds prompts for different model types and use cases"""
    
    @staticmethod
    def build_rewrite_prompt(text: str, mood: str, allow_profanity: bool) -> str:
        """Build prompt for text rewriting"""
        system_prompt = (
            ConfigManager.load_system_prompt() or 
            "You are a concise rewrite assistant. Improve clarity and tone. Keep factual content."
        )
        
        if not allow_profanity:
            system_prompt += " Avoid profanity."
        system_prompt += " Do NOT echo or restate these instructions; output only the rewritten text."
        
        user_prompt = (
            f"Rewrite the text clearly. Keep short sentences.\n"
            f"Mood: {mood or 'neutral'}\n\n"
            f"Text:\n{text}"
        )
        
        if ModelDetector.is_phi3_family():
            return (
                f"<|system|>\n{system_prompt}\n<|end|>\n"
                f"<|user|>\n{user_prompt}\n<|end|>\n"
                f"<|assistant|>\n"
            )
        else:
            return f"<s>[INST] <<SYS>>{system_prompt}<</SYS>>\n{user_prompt} [/INST]"
    
    @staticmethod
    def get_persona_descriptor(persona: str) -> str:
        """Get personality description for persona"""
        persona_lower = (persona or "").strip().lower()
        
        persona_map = {
            "dude": "laid-back, mellow, calm confidence; avoids jokes.",
            "chick": "sassy, clever, stylish; crisp phrasing.",
            "nerd": "precise, witty, techy; low fluff.",
            "rager": "angry, intense bursts; may be edgy.",
            "comedian": "quippy and playful; jokes allowed.",
            "jarvis": "polished, butler tone; concise.",
            "ops": "terse, incident commander; direct.",
            "action": "stoic mission-brief style; clipped.",
            "tappit": "rough, brash, Afrikaans slang; cheeky, blunt, playful but can be rude."
        }
        
        return persona_map.get(persona_lower, "neutral, subtle tone.")
    
    @classmethod
    def build_riff_prompt(cls, persona: str, subject: str, allow_profanity: bool) -> str:
        """Build prompt for persona riffs"""
        persona_desc = cls.get_persona_descriptor(persona)
        profanity_rule = "" if allow_profanity else " Avoid profanity."
        
        system_prompt = (
            f"Persona style: {persona_desc}\n"
            f"Write 1–3 short one-liners (≤140 chars). No bullets, lists, or meta.{profanity_rule}"
        ).strip()
        
        user_prompt = f"Subject: {subject or 'Status update'}\nWrite up to 3 short lines."
        
        if ModelDetector.is_phi3_family():
            return (
                f"<|system|>\n{system_prompt}\n<|end|>\n"
                f"<|user|>\n{user_prompt}\n<|end|>\n"
                f"<|assistant|>\n"
            )
        else:
            return f"<s>[INST] <<SYS>>{system_prompt}<</SYS>>\n{user_prompt} [/INST]"
    
    @staticmethod
    def build_chat_prompt(messages: List[Dict[str, str]], system_prompt: str = "") -> str:
        """Build prompt for chat conversation"""
        system_text = (
            system_prompt or 
            ConfigManager.load_system_prompt() or 
            "You are a helpful assistant."
        ).strip()
        
        if ModelDetector.is_phi3_family():
            parts = []
            if system_text:
                parts.append(f"<|system|>\n{system_text}\n<|end|>")
            
            for message in messages:
                role = (message.get("role") or "").lower()
                content = (message.get("content") or "").strip()
                
                if not content:
                    continue
                
                if role == "user":
                    parts.append(f"<|user|>\n{content}\n<|end|>")
                elif role == "assistant":
                    parts.append(f"<|assistant|>\n{content}\n<|end|>")
            
            parts.append("<|assistant|>\n")
            return "\n".join(parts)
        else:
            conversation = []
            if system_text:
                conversation.append(f"<<SYS>>{system_text}<</SYS>>")
            
            for message in messages:
                role = (message.get("role") or "").lower()
                content = (message.get("content") or "").strip()
                
                if not content:
                    continue
                
                if role == "user":
                    conversation.append(f"[USER]\n{content}")
                elif role == "assistant":
                    conversation.append(f"[ASSISTANT]\n{content}")
            
            conversation.append("[/INST]")
            return "<s>[INST] " + "\n".join(conversation) + "\n[ASSISTANT]\n"

# ============================
# RAG Integration
# ============================

class RAGIntegrator:
    """Handles RAG (Retrieval Augmented Generation) integration"""
    
    @staticmethod
    def build_prompt_with_context(messages: List[Dict[str, str]], 
                                 system_preamble: str = "") -> Tuple[List[Dict[str, str]], str]:
        """Add RAG context to chat messages"""
        # Find last user message
        last_user_message = ""
        for message in reversed(messages or []):
            if (message.get("role") or "").lower() == "user":
                content = (message.get("content") or "").strip()
                if content:
                    last_user_message = content
                    break
        
        # Get context from RAG
        context = inject_context(last_user_message, top_k=5) if last_user_message else inject_context("", top_k=5)
        
        # Build enhanced system prompt
        rag_instruction = (
            "Prefer the supplied facts over stale memory. "
            "If facts include times, mention freshness. "
            "Do not invent entities not present in Context."
        )
        
        enhanced_system = (system_preamble or "").strip()
        if enhanced_system:
            enhanced_system += "\n\n"
        enhanced_system += rag_instruction
        
        if context:
            enhanced_system += f"\n\nContext:\n{context}"
        else:
            enhanced_system += "\n\nContext:\n(none)"
        
        return messages, enhanced_system

# ============================
# Lexicon Fallback System
# ============================

class LexiconFallback:
    """Provides deterministic fallback responses when LLM is unavailable"""
    
    _LRU_MAX_SIZE = 32
    _lru_cache: deque[str] = deque(maxlen=_LRU_MAX_SIZE)
    _seen_phrases: set[str] = set()
    
    @staticmethod
    def _generate_seed(subject: str) -> int:
        """Generate deterministic seed from subject"""
        hash_obj = hashlib.sha1((subject or "").lower().encode("utf-8"))
        return int(hash_obj.hexdigest()[:8], 16)
    
    @classmethod
    def _get_phrase_banks(cls, allow_profanity: bool) -> Dict[str, List[str]]:
        """Get categorized phrase banks"""
        banks = {
            "ack": [
                "noted", "synced", "logged", "captured", "tracked", "queued",
                "recorded", "acknowledged", "on file", "in the book", "added to ledger", "received"
            ],
            "status": [
                "backup verified", "run completed", "snapshot created", "no changes", "deltas applied",
                "errors detected", "all clear", "integrity check passed", "checksum ok", "retention rotated"
            ],
            "action": [
                "will retry", "escalating", "re-queueing", "throttling IO", "cooldown engaged",
                "next window scheduled", "compacting catalogs", "purging temp", "rotating keys", "rebuilding index"
            ],
            "humor": [
                "beep boop paperwork", "robots hate dust", "bits behaving", "sleep is for disks",
                "coffee-fueled checksum", "backups doing backups"
            ]
        }
        
        # Note: Profanity handling could be added here if needed
        return banks
    
    @classmethod
    def _get_templates(cls) -> List[str]:
        """Get response templates"""
        return [
            "{subj}: {ack}. {status}. Lexi.",
            "{subj}: {status}. {action}. Lexi.",
            "{subj}: {ack} — {status}. Lexi.",
            "{subj}: {status}. Lexi."
        ]
    
    @classmethod
    def _get_subject_weights(cls, subject: str) -> Dict[str, float]:
        """Get phrase weights based on subject content"""
        subject_lower = (subject or "").lower()
        
        if re.search(r"(duplicati|backup|snapshot|restore|archive)", subject_lower):
            return {"ack": 1.2, "status": 1.6, "action": 1.0, "humor": 0.5}
        
        if re.search(r"(uptime|monitor|alert|incident|sev|failure|error)", subject_lower):
            return {"ack": 1.1, "status": 1.4, "action": 1.3, "humor": 0.4}
        
        return {"ack": 1.0, "status": 1.0, "action": 1.0, "humor": 0.6}
    
    @classmethod
    def _pick_phrase(cls, rng, phrases: List[str], avoid: set[str]) -> str:
        """Pick a phrase while avoiding recently used ones"""
        for _ in range(5):  # Try up to 5 times to avoid repeats
            candidate = rng.choice(phrases)
            if candidate not in avoid:
                return candidate
        return rng.choice(phrases)  # Fallback if all are in avoid set
    
    @classmethod
    def _compose_line(cls, subject: str, allow_profanity: bool) -> str:
        """Compose a single lexicon line"""
        import random
        
        clean_subject = subject.strip()
        phrase_banks = cls._get_phrase_banks(allow_profanity)
        weights = cls._get_subject_weights(clean_subject)
        rng = random.Random(cls._generate_seed(clean_subject))
        
        # Build weighted phrase pools
        phrase_pools = {}
        for category, base_phrases in phrase_banks.items():
            weight = weights.get(category, 1.0)
            multiplier = int(max(1, round(3 * weight)))
            phrase_pools[category] = base_phrases * multiplier
        
        template = rng.choice(cls._get_templates())
        avoid_set = set(cls._lru_cache)
        
        # Pick phrases
        selections = {}
        for category in ("ack", "status", "action", "humor"):
            if f"{{{category}}}" in template:
                pool = phrase_pools.get(category, [])
                if pool:
                    selections[category] = cls._pick_phrase(rng, pool, avoid_set)
        
        # Format line
        line = template.format(
            subj=clean_subject,
            **{k: v for k, v in selections.items() if v is not None}
        )
        
        # Clean up formatting
        line = re.sub(r"\s{2,}", " ", line).strip()
        if len(line) > 140:
            line = line[:140].rstrip()
        
        # Update LRU cache
        for phrase in selections.values():
            if phrase:
                cls._lru_cache.append(phrase)
                cls._seen_phrases.add(phrase)
        
        return line
    
    @classmethod
    def generate_lines(cls, persona: str, subject: str, max_lines: int, 
                      allow_profanity: bool) -> List[str]:
        """Generate multiple lexicon fallback lines"""
        clean_subject = TextProcessor.strip_transport_tags(
            TextProcessor.scrub_persona_tokens(subject or "Update")
        ).strip()
        
        lines = []
        used_lines = set()
        
        for _ in range(max(1, max_lines or 3)):
            line = cls._compose_line(clean_subject, allow_profanity)
            if line not in used_lines:
                used_lines.add(line)
                lines.append(line)
        
        return lines[:max_lines]

# ============================
# Core Generation Engine
# ============================

class GenerationEngine:
    """Core text generation functionality"""
    
    @staticmethod
    def _setup_timeout_handler():
        """Setup signal handler for generation timeout"""
        def timeout_handler(signum, frame):
            raise TimeoutError("Generation timeout")
        
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, timeout_handler)
    
    @classmethod
    def generate(cls, prompt: str, params: GenerationParams, model_config: ModelConfig) -> str:
        """Main generation function that routes to appropriate backend"""
        stops = ModelDetector.get_stop_tokens()
        use_grammar = ModelDetector.should_use_grammar_auto()
        
        if _state.mode == LLMMode.OLLAMA and _state.ollama_url:
            model_name = (
                model_config.name_hint if (
                    model_config.name_hint and 
                    "/" not in model_config.name_hint and 
                    not model_config.name_hint.endswith(".gguf")
                ) else OllamaBackend.extract_model_name(model_config.url)
            )
            
            return OllamaBackend.generate(
                _state.ollama_url, model_name, prompt, params, stops
            )
        
        elif _state.mode == LLMMode.LLAMA and _state.llm is not None:
            return LlamaBackend.generate(prompt, params, stops, use_grammar)
        
        return ""

# ============================
# Public API Functions
# ============================

def ensure_loaded(
    *,
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    ctx_tokens: int = 4096,
    cpu_limit: int = 80,
    hf_token: Optional[str] = None,
    base_url: str = ""
) -> bool:
    """Ensure model is loaded and ready for generation"""
    # Get profile settings (EnviroGuard has priority)
    profile = ProfileManager.resolve_current_profile()
    ctx_tokens = profile.ctx_tokens
    cpu_limit = profile.cpu_percent
    _state.default_ctx = max(1024, ctx_tokens)
    
    _log(f"ensure_loaded using profile='{profile.name}' ctx={ctx_tokens} cpu_limit%={cpu_limit}")
    
    with _lock_manager.acquire_with_timeout() as acquired:
        if not acquired:
            _log("Failed to acquire lock for model loading")
            return False
        
        base_url = base_url.strip()
        
        # Try Ollama first if base_url provided
        if base_url:
            _state.ollama_url = base_url
            if OllamaBackend.check_availability(base_url):
                _state.mode = LLMMode.OLLAMA
                _state.llm = None
                _state.loaded_model_path = None
                _state.model_name_hint = model_path or ""
                _log(f"Using Ollama at {base_url}")
                return True
            else:
                _log(f"Ollama not reachable at {base_url}; falling back to local mode")
        
        # Reset state for local loading
        _state.mode = LLMMode.NONE
        _state.ollama_url = ""
        _state.llm = None
        _state.loaded_model_path = None
        
        # Resolve model configuration
        model_url, model_path, hf_token = ModelManager.resolve_from_options(
            model_url, model_path, hf_token
        )
        
        if not (model_url or model_path):
            _log("No model_url/model_path resolved from options; cannot load model")
            return False
        
        _state.model_name_hint = model_path or ""
        _log(f"Model resolve -> url='{os.path.basename(model_url) if model_url else ''}' path='{model_path}'")
        
        # Ensure model is available locally
        local_model_path = ModelManager.ensure_local_model(
            model_url, model_path, hf_token, model_sha256 or ""
        )
        if not local_model_path:
            _log("ensure_local_model failed")
            return False
        
        # Load model with llama-cpp-python
        options = ConfigManager.read_options()
        success = LlamaBackend.load_model(local_model_path, _state.default_ctx, cpu_limit, options)
        return success


def rewrite(
    *,
    text: str,
    mood: str = "neutral",
    timeout: int = 12,
    cpu_limit: int = 80,
    models_priority: Optional[str] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    allow_profanity: bool = False,
    ctx_tokens: int = 4096,
    hf_token: Optional[str] = None,
    max_lines: int = 0,
    max_chars: int = 0
) -> str:
    """Rewrite text with specified mood and constraints"""
    profile = ProfileManager.resolve_current_profile()
    ctx_tokens = profile.ctx_tokens
    cpu_limit = profile.cpu_percent
    timeout = profile.timeout_seconds
    
    options = ConfigManager.read_options()
    rewrite_max_tokens = ConfigManager.get_int_opt(options, "llm_rewrite_max_tokens", 256)
    _log(f"rewrite: effective max_tokens={rewrite_max_tokens}")
    
    with _lock_manager.acquire_with_timeout(timeout) as acquired:
        if not acquired:
            _log("Failed to acquire lock for rewrite")
            return text
        
        # Ensure model is loaded
        if _state.mode == LLMMode.NONE:
            success = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=ctx_tokens,
                cpu_limit=cpu_limit,
                hf_token=hf_token,
                base_url=base_url
            )
            if not success:
                return text
        
        # Build prompt and check context overflow
        prompt = PromptBuilder.build_rewrite_prompt(text, mood, allow_profanity)
        _log(f"rewrite: effective timeout={timeout}s")
        
        input_tokens = ContextManager.get_token_count(prompt)
        _log(f"rewrite: prompt_tokens={input_tokens}")
        
        if ContextManager.check_overflow(input_tokens, rewrite_max_tokens, ctx_tokens, reserve=256):
            _log(f"rewrite: ctx precheck overflow (prompt={input_tokens}, out={rewrite_max_tokens}, ctx={ctx_tokens}) → return original text")
            return text
        
        # Generate
        params = GenerationParams(
            max_tokens=rewrite_max_tokens,
            timeout=timeout
        )
        model_config = ModelConfig(url=model_url, path=model_path, name_hint=model_path)
        
        output = GenerationEngine.generate(prompt, params, model_config)
        final_text = output if output else text
    
    # Post-process
    final_text = TextProcessor.strip_meta_markers(final_text)
    if max_lines:
        final_text = TextProcessor.trim_lines(final_text, max_lines)
    if max_chars:
        final_text = TextProcessor.soft_trim_chars(final_text, max_chars)
    
    return final_text


def riff(
    *,
    subject: str,
    persona: str = "neutral",
    timeout: int = 8,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    allow_profanity: bool = False
) -> str:
    """Generate a short riff response (legacy interface)"""
    subject = TextProcessor.strip_transport_tags(
        TextProcessor.scrub_persona_tokens(subject or "")
    )
    
    lines = persona_riff(
        persona=persona,
        context=f"Subject: {subject}",
        max_lines=3,
        timeout=timeout,
        base_url=base_url,
        model_url=model_url,
        model_path=model_path,
        allow_profanity=allow_profanity
    )
    
    joined = "\n".join(lines[:3]) if lines else ""
    if len(joined) > 120:
        joined = joined[:119].rstrip() + "…"
    
    return joined


def persona_riff(
    *,
    persona: str,
    context: str,
    max_lines: int = 3,
    timeout: int = 8,
    cpu_limit: int = 80,
    models_priority: Optional[List[str]] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    allow_profanity: Optional[bool] = None,
    ctx_tokens: int = 4096,
    hf_token: Optional[str] = None
) -> List[str]:
    """Generate persona-based riff lines"""
    # Determine profanity setting
    if allow_profanity is None:
        env_allow = os.getenv("PERSONALITY_ALLOW_PROFANITY", "false").lower() in ("1", "true", "yes")
        persona_is_rager = (persona or "").lower().strip() == "rager"
        allow_profanity = env_allow and persona_is_rager
    
    # Clean context
    context = TextProcessor.sanitize_context_subject(context)
    
    # Get configuration
    options = ConfigManager.read_options()
    llm_enabled = ConfigManager.get_bool_opt(options, "llm_enabled", True)
    riffs_enabled = ConfigManager.get_bool_opt(options, "llm_persona_riffs_enabled", True)
    riff_max_tokens = ConfigManager.get_int_opt(options, "llm_riff_max_tokens", 32)
    
    _log(f"persona_riff: effective max_tokens={riff_max_tokens}")
    
    # Extract subject for fallback
    subject = TextProcessor.extract_subject_from_context(context or "")
    
    # Use lexicon fallback if LLM disabled
    if not llm_enabled and riffs_enabled:
        return LexiconFallback.generate_lines(persona, subject, max_lines, allow_profanity)
    
    # Get profile settings
    profile = ProfileManager.resolve_current_profile()
    ctx_tokens = profile.ctx_tokens
    cpu_limit = profile.cpu_percent
    timeout = profile.timeout_seconds
    
    with _lock_manager.acquire_with_timeout(timeout) as acquired:
        if not acquired:
            _log("Failed to acquire lock for persona_riff")
            return LexiconFallback.generate_lines(persona, subject, max_lines, allow_profanity) if riffs_enabled else []
        
        # Ensure model is loaded
        if _state.mode == LLMMode.NONE:
            if llm_enabled:
                success = ensure_loaded(
                    model_url=model_url,
                    model_path=model_path,
                    model_sha256=model_sha256,
                    ctx_tokens=ctx_tokens,
                    cpu_limit=cpu_limit,
                    hf_token=hf_token,
                    base_url=base_url
                )
                if not success:
                    return LexiconFallback.generate_lines(persona, subject, max_lines, allow_profanity) if riffs_enabled else []
            else:
                return LexiconFallback.generate_lines(persona, subject, max_lines, allow_profanity) if riffs_enabled else []
        
        if _state.mode not in (LLMMode.LLAMA, LLMMode.OLLAMA):
            return LexiconFallback.generate_lines(persona, subject, max_lines, allow_profanity) if riffs_enabled else []
        
        # Build prompt
        persona_desc = PromptBuilder.get_persona_descriptor(persona)
        system_parts = [
            f"Persona style: {persona_desc}",
            f"Write up to {max_lines} distinct one-liners. Each ≤ 140 chars. No bullets, numbering, lists, labels, JSON, or meta.",
        ]
        
        if allow_profanity is False:
            system_parts.append("Avoid profanity.")
        
        system_prompt = " ".join(part for part in system_parts if part).strip()
        user_prompt = f"{context.strip()}\n\nWrite up to {max_lines} short lines in the requested voice."
        
        if ModelDetector.is_phi3_family():
            prompt = (
                f"<|system|>\n{system_prompt}\n<|end|>\n"
                f"<|user|>\n{user_prompt}\n<|end|>\n"
                f"<|assistant|>\n"
            )
        else:
            prompt = f"<s>[INST] <<SYS>>{system_prompt}<</SYS>>\n{user_prompt} [/INST]"
        
        # Check context overflow
        _log(f"persona_riff: effective timeout={timeout}s")
        input_tokens = ContextManager.get_token_count(prompt)
        _log(f"persona_riff: prompt_tokens={input_tokens}")
        
        if ContextManager.check_overflow(input_tokens, riff_max_tokens, ctx_tokens, reserve=256):
            _log(f"persona_riff: ctx precheck overflow (prompt={input_tokens}, out={riff_max_tokens}, ctx={ctx_tokens}) → Lexi")
            return LexiconFallback.generate_lines(persona, subject, max_lines, allow_profanity) if riffs_enabled else []
        
        # Generate
        params = GenerationParams(max_tokens=riff_max_tokens, timeout=timeout)
        model_config = ModelConfig(url=model_url, path=model_path, name_hint=model_path)
        
        raw_output = GenerationEngine.generate(prompt, params, model_config)
        if not raw_output:
            return LexiconFallback.generate_lines(persona, subject, max_lines, allow_profanity) if riffs_enabled else []
    
    # Process output
    lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
    
    # Clean lines
    cleaned_lines = []
    for line in lines:
        line = TextProcessor.strip_transport_tags(line)
        line = TextProcessor.scrub_persona_tokens(line)
        line = TextProcessor.strip_meta_markers(line)
        line = line.strip().strip('"').strip("'")
        line = re.sub(r'^\s*[-•*]\s*', '', line)  # Remove bullet points
        if line:
            cleaned_lines.append(line)
    
    # Deduplicate and limit
    final_lines = []
    seen = set()
    
    for line in cleaned_lines:
        line = line.lstrip("-•* ").strip()
        if not line:
            continue
        
        if len(line) > 140:
            line = line[:140].rstrip()
        
        line = TextProcessor.trim_to_sentence(line, 140)
        line_key = line.lower()
        
        if line_key in seen or not line:
            continue
        
        seen.add(line_key)
        final_lines.append(line)
        
        if len(final_lines) >= max(1, max_lines or 3):
            break
    
    # Fallback if no lines generated
    if not final_lines and riffs_enabled:
        return LexiconFallback.generate_lines(persona, subject, max_lines, allow_profanity)
    
    return final_lines


def persona_riff_ex(
    *,
    persona: str,
    context: str,
    max_lines: int = 3,
    timeout: int = 8,
    cpu_limit: int = 80,
    models_priority: Optional[List[str]] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    allow_profanity: Optional[bool] = None,
    ctx_tokens: int = 4096,
    hf_token: Optional[str] = None
) -> Tuple[List[str], str]:
    """Extended riff that reports generation source (llm/lexicon)"""
    options = ConfigManager.read_options()
    llm_enabled = ConfigManager.get_bool_opt(options, "llm_enabled", True)
    riffs_enabled = ConfigManager.get_bool_opt(options, "llm_persona_riffs_enabled", True)
    
    context = TextProcessor.sanitize_context_subject(context)
    subject = TextProcessor.extract_subject_from_context(context or "")
    
    if not llm_enabled and riffs_enabled:
        lines = LexiconFallback.generate_lines(
            persona, subject, max_lines, 
            allow_profanity if allow_profanity is not None else False
        )
        return lines, "lexicon"
    
    lines = persona_riff(
        persona=persona,
        context=context,
        max_lines=max_lines,
        timeout=timeout,
        cpu_limit=cpu_limit,
        models_priority=models_priority,
        base_url=base_url,
        model_url=model_url,
        model_path=model_path,
        model_sha256=model_sha256,
        allow_profanity=allow_profanity,
        ctx_tokens=ctx_tokens,
        hf_token=hf_token
    )
    
    # Determine source based on whether we got lines and fallback usage
    source = "llm" if lines else "lexicon"
    return lines, source


def chat_generate(
    *,
    messages: List[Dict[str, str]],
    system_prompt: str = "",
    max_new_tokens: int = 384,
    timeout: Optional[int] = None,
    base_url: str = "",
    model_url: str = "",
    model_path: str = "",
    model_sha256: str = "",
    hf_token: Optional[str] = None
) -> str:
    """Generate chat response with RAG integration"""
    options = ConfigManager.read_options()
    if not ConfigManager.get_bool_opt(options, "llm_enabled", True):
        return ""
    
    if not messages or not isinstance(messages, list):
        return ""
    
    # Validate last message is from user
    last_message = messages[-1]
    if (last_message.get("role") or "").lower() != "user":
        return ""
    
    if not (last_message.get("content") or "").strip():
        return ""
    
    # Get profile settings
    profile = ProfileManager.resolve_current_profile()
    ctx_tokens = profile.ctx_tokens
    effective_timeout = timeout if timeout is not None else profile.timeout_seconds
    
    with _lock_manager.acquire_with_timeout(effective_timeout) as acquired:
        if not acquired:
            _log("Failed to acquire lock for chat_generate")
            return ""
        
        # Ensure model is loaded
        if _state.mode == LLMMode.NONE:
            success = ensure_loaded(
                model_url=model_url,
                model_path=model_path,
                model_sha256=model_sha256,
                ctx_tokens=ctx_tokens,
                cpu_limit=profile.cpu_percent,
                hf_token=hf_token,
                base_url=base_url
            )
            if not success:
                return ""
        
        # Add RAG context to system prompt
        enhanced_messages, enhanced_system_prompt = RAGIntegrator.build_prompt_with_context(
            messages, system_preamble=system_prompt
        )
        
        # Build chat prompt
        prompt = PromptBuilder.build_chat_prompt(enhanced_messages, enhanced_system_prompt)
        
        # Check context overflow
        input_tokens = ContextManager.get_token_count(prompt)
        if ContextManager.check_overflow(input_tokens, max_new_tokens, ctx_tokens, reserve=256):
            _log("chat_generate: ctx overflow → refuse generation")
            return ""
        
        # Generate
        params = GenerationParams(
            max_tokens=max_new_tokens,
            timeout=max(4, effective_timeout)
        )
        model_config = ModelConfig(url=model_url, path=model_path, name_hint=model_path)
        
        output = GenerationEngine.generate(prompt, params, model_config)
    
    return TextProcessor.strip_meta_markers(output or "").strip()


# ============================
# Self-test and Diagnostics
# ============================

def run_self_test() -> None:
    """Run diagnostic self-test"""
    print("llm_client self-check start")
    try:
        profile = ProfileManager.resolve_current_profile()
        _log(f"SELFTEST profile -> name={profile.name} cpu={profile.cpu_percent} "
             f"ctx={profile.ctx_tokens} timeout={profile.timeout_seconds}")
        
        demo_lines = LexiconFallback.generate_lines(
            "jarvis", 
            "Duplicati Backup report for misc: nerd. comedian.", 
            2, 
            allow_profanity=False
        )
        
        for line in demo_lines:
            _log(f"LEXI: {line}")
            
    except Exception as e:
        print(f"self-check error: {e}")
    
    print("llm_client self-check end")


if __name__ == "__main__":
    run_self_test()
