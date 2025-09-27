from __future__ import annotations
import re, json, importlib, html, os
from typing import List, Tuple, Optional, Dict, Any, Protocol, NamedTuple
from urllib.parse import unquote_plus, parse_qs
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from functools import lru_cache
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------- Data Structures --------
@dataclass
class ProcessingResult:
    """Encapsulates the result of message processing"""
    text: str
    extras: Dict[str, Any]
    images: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class MessageContext:
    """Encapsulates message processing context"""
    title: str
    body: str
    source_hint: Optional[str] = None
    persona: Optional[str] = None
    extras_in: Optional[Dict[str, Any]] = None
    mood: str = "neutral"
    mode: str = "standard"
    persona_quip: bool = True

# -------- Configuration Manager --------
class ConfigManager:
    """Centralized configuration management with caching"""
    
    def __init__(self):
        self._config_cache = {}
        self._last_modified = {}
    
    @lru_cache(maxsize=32)
    def get_options(self) -> Dict[str, Any]:
        """Load options with caching"""
        try:
            with open("/data/options.json", "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load options: {e}")
            return {}
    
    def get_bool(self, key: str, default: bool = False, env_names: List[str] = None) -> bool:
        """Get boolean value with env variable fallback"""
        # Check environment variables first
        if env_names:
            for env_name in env_names:
                env_val = os.getenv(env_name, "").strip().lower()
                if env_val in ("1", "true", "yes", "on"):
                    return True
                elif env_val in ("0", "false", "no", "off"):
                    return False
        
        # Check options file
        options = self.get_options()
        try:
            val = str(options.get(key, default)).strip().lower()
            return val in ("1", "true", "yes", "on")
        except Exception:
            return default
    
    def get_int(self, key: str, default: int, env_name: str = None) -> int:
        """Get integer value with env variable fallback"""
        if env_name:
            try:
                return int(os.getenv(env_name, str(default)))
            except ValueError:
                pass
        
        options = self.get_options()
        try:
            return int(options.get(key, default))
        except (ValueError, TypeError):
            return default
    
    @property
    def beautify_enabled(self) -> bool:
        return not self.get_bool("beautify_disabled", False, ["BEAUTIFY_DISABLED"])
    
    @property
    def llm_riffs_enabled(self) -> bool:
        return self.get_bool("llm_persona_riffs_enabled", True, ["BEAUTIFY_LLM_ENABLED", "llm_enabled"])
    
    @property
    def personality_enabled(self) -> bool:
        return self.get_bool("personality_enabled", True, ["PERSONALITY_ENABLED"])
    
    @property
    def llm_rewrite_enabled(self) -> bool:
        return self.get_bool("llm_rewrite_enabled", False)
    
    @property
    def max_message_length(self) -> int:
        return self.get_int("max_message_length", 3500, "BEAUTIFY_MAX_LEN")
    
    @property
    def rewrite_max_chars(self) -> int:
        return self.get_int("llm_message_rewrite_max_chars", 350)

# Global config instance
config = ConfigManager()

# -------- Text Processing Utilities --------
class TextProcessor:
    """Handles text cleaning and normalization"""
    
    # Compiled regex patterns for better performance
    IMG_URL_RE = re.compile(r'(https?://[^\s)]+?\.(?:png|jpg|jpeg|gif|webp)(?:\?[^\s)]*)?)', re.I)
    MD_IMG_RE = re.compile(r'!\[([^\]]*)\]\s*\(\s*<?\s*(https?://[^\s)]+?)\s*>?\s*\)', re.I | re.S)
    KV_RE = re.compile(r'^\s*([A-Za-z0-9 _\-\/\.]+?)\s*[:=]\s*(.+)$', re.M)
    TS_RE = re.compile(r'(?:(?:date(?:/time)?|time)\s*[:\-]\s*)?(\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', re.I)
    IP_RE = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{2})\b')
    EMOJI_RE = re.compile("[\U0001F300-\U0001F6FF\U0001F900-\U0001F9FF\U00002600-\U000026FF\U00002700-\U000027BF\U0001FA70-\U0001FAFF\U0001F1E6-\U0001F1FF]")
    NOISE_RE = re.compile(r'^\s*(?:sent from .+|via .+ api|automated message|do not reply)\.?\s*$', re.I)
    MIME_HEADER_RE = re.compile(r'^\s*Content-(?:Disposition|Type|Length|Transfer-Encoding)\s*:.*$', re.I | re.M)
    ACTION_SAYS_RE = re.compile(r'^\s*action\s+says:\s*.*$', re.I | re.M)
    META_LINE_RE = re.compile(r'^\s*(?:tone|rule|rules|guidelines?|style(?:\s*hint)?|instruction|instructions|system(?:\s*prompt)?|persona|respond(?:\s*with)?|produce\s*only)\s*[:\-]', re.I)
    
    @classmethod
    def strip_noise(cls, text: str) -> str:
        """Remove common noise patterns"""
        if not text:
            return ""
        
        s = cls.EMOJI_RE.sub("", text)
        lines = [line for line in s.splitlines() if not cls.NOISE_RE.match(line)]
        return "\n".join(lines)
    
    @classmethod
    def normalize_whitespace(cls, text: str) -> str:
        """Normalize whitespace and line breaks"""
        if not text:
            return ""
        
        s = text.replace("\t", "  ")
        s = re.sub(r'[ \t]+$', "", s, flags=re.M)
        s = re.sub(r'\n{3,}', '\n\n', s)
        return s.strip()
    
    @classmethod
    def extract_images(cls, text: str) -> Tuple[str, List[str], List[str]]:
        """Extract images while preserving meaning through alt text"""
        if not text:
            return "", [], []
        
        urls, alts = [], []
        
        def replace_markdown_img(match):
            alt = (match.group(1) or "").strip()
            url = match.group(2)
            alts.append(alt)
            urls.append(url)
            return f"[image: {alt}]" if alt else "[image]"
        
        def replace_bare_url(match):
            url = match.group(1).rstrip('.,;:)]>"\'')
            urls.append(url)
            return ""
        
        text = cls.MD_IMG_RE.sub(replace_markdown_img, text)
        text = cls.IMG_URL_RE.sub(replace_bare_url, text)
        
        # Deduplicate URLs, preferring poster hosts
        unique_urls = []
        seen = set()
        poster_hosts = {"githubusercontent.com", "fanart.tv", "themoviedb.org", "image.tmdb.org"}
        
        for url in sorted(urls, key=lambda u: (0 if any(h in u.lower() for h in poster_hosts) else 1)):
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return text.strip(), unique_urls, alts
    
    @classmethod
    def safe_truncate(cls, text: str, max_len: int = 3500) -> str:
        """Truncate without breaking markdown structures"""
        if len(text) <= max_len:
            return text
        
        # Find protected regions (code blocks, links, images)
        protected_patterns = [
            re.compile(r'```.*?```', re.S),
            re.compile(r'\[[^\]]+?\]\([^)]+?\)'),
            cls.IMG_URL_RE
        ]
        
        protected_ranges = []
        for pattern in protected_patterns:
            for match in pattern.finditer(text):
                protected_ranges.append((match.start(), match.end()))
        
        protected_ranges.sort()
        
        # Truncate safely
        pos = 0
        result = []
        used = 0
        
        for start, end in protected_ranges:
            if start > pos:
                chunk = text[pos:start]
                if used + len(chunk) > max_len:
                    remaining = max_len - used - 15  # Reserve space for "...(truncated)"
                    if remaining > 0:
                        safe_cut = max(chunk.rfind("\n"), chunk.rfind(" "))
                        if safe_cut > remaining * 0.6:
                            chunk = chunk[:safe_cut]
                        else:
                            chunk = chunk[:remaining]
                        result.append(chunk.rstrip() + "\n\n...(truncated)")
                    return "".join(result)
                result.append(chunk)
                used += len(chunk)
            
            segment = text[start:end]
            if used + len(segment) > max_len:
                result.append("\n\n...(truncated)")
                return "".join(result)
            
            result.append(segment)
            used += len(segment)
            pos = end
        
        if pos < len(text):
            remaining_text = text[pos:]
            if used + len(remaining_text) <= max_len:
                result.append(remaining_text)
            else:
                available = max_len - used - 15
                if available > 0:
                    safe_cut = max(remaining_text.rfind("\n"), remaining_text.rfind(" "))
                    if safe_cut > available * 0.6:
                        remaining_text = remaining_text[:safe_cut]
                    else:
                        remaining_text = remaining_text[:available]
                    result.append(remaining_text.rstrip() + "\n\n...(truncated)")
        
        return "".join(result)

# -------- Message Type Handlers --------
class MessageHandler(ABC):
    """Abstract base class for message type handlers"""
    
    @abstractmethod
    def can_handle(self, context: MessageContext) -> bool:
        """Check if this handler can process the given message"""
        pass
    
    @abstractmethod
    def process(self, context: MessageContext) -> ProcessingResult:
        """Process the message and return formatted result"""
        pass

class WatchtowerHandler(MessageHandler):
    """Handler for Watchtower Docker update messages"""
    
    HOST_PATTERN = re.compile(r'\bupdates?\s+on\s+([A-Za-z0-9._-]+)', re.I)
    UPDATE_PATTERNS = [
        re.compile(r'^\s*[-*]\s*(?P<name>/?[A-Za-z0-9._-]+)\s*(?P<img>[^)]+)\s*:\s*(?P<old>[0-9a-f]{7,64})\s+updated\s+to\s+(?P<new>[0-9a-f]{7,64})\s*$', re.I),
        re.compile(r'^\s*[-*]\s*(?P<name>/?[A-Za-z0-9._-]+)\s*:\s*(?P<old>[0-9a-f]{7,64})\s+updated\s+to\s+(?P<new>[0-9a-f]{7,64})\s*$', re.I),
    ]
    FRESH_PATTERN = re.compile(r':\s*Fresh\s*$', re.I)
    
    def can_handle(self, context: MessageContext) -> bool:
        text = f"{context.title} {context.body}".lower()
        return "watchtower" in text
    
    def process(self, context: MessageContext) -> ProcessingResult:
        # Extract host information
        host_match = self.HOST_PATTERN.search(context.title or "")
        host = host_match.group(1) if host_match else "unknown"
        
        # Parse updates
        updates = []
        other_lines = []
        
        for line in (context.body or "").splitlines():
            if self.FRESH_PATTERN.search(line):
                continue
            
            matched = False
            for pattern in self.UPDATE_PATTERNS:
                match = pattern.match(line)
                if match:
                    groups = match.groupdict()
                    updates.append({
                        'name': groups.get('name', '').strip(),
                        'image': groups.get('img', groups.get('name', '')).strip(),
                        'old_hash': groups.get('old', '').strip(),
                        'new_hash': groups.get('new', '').strip()
                    })
                    matched = True
                    break
            
            if not matched and line.strip():
                other_lines.append(line)
        
        # Build markdown
        lines = [f"📟 Jarvis Prime", "", f"**Host:** `{host}`"]
        
        if not updates:
            lines.append("\n_No updates (all images fresh)._")
        else:
            lines.extend(["", f"**Updated ({len(updates)}):**"])
            for update in updates:
                lines.append(f"• `{update['name']}` → `{update['image']}`")
                lines.append(f"   old: `{update['old_hash']}` → new: `{update['new_hash']}`")
        
        metadata = {
            "watchtower::host": host,
            "watchtower::updated_count": len(updates),
            "watchtower::has_updates": len(updates) > 0
        }
        
        extras = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": f"Jarvis Prime: Watchtower Updates",
            "jarvis::beautified": True,
            "jarvis::handler": "watchtower"
        }
        
        return ProcessingResult(
            text="\n".join(lines),
            extras=extras,
            metadata=metadata
        )

class StandardHandler(MessageHandler):
    """Handler for standard messages"""
    
    def can_handle(self, context: MessageContext) -> bool:
        return True  # Default handler accepts everything
    
    def process(self, context: MessageContext) -> ProcessingResult:
        processor = TextProcessor()
        
        # Clean and process text
        cleaned_body = processor.strip_noise(context.body or "")
        normalized_body = processor.normalize_whitespace(cleaned_body)
        normalized_body = html.unescape(normalized_body)
        
        # Extract images
        body_without_images, images, image_alts = processor.extract_images(normalized_body)
        
        # Detect message severity
        severity_badge = self._get_severity_badge(context.title, body_without_images)
        
        # Build formatted message
        lines = [f"📟 Jarvis Prime {severity_badge}".rstrip()]
        
        # Add subject if present
        clean_subject = self._clean_subject(context.title, body_without_images)
        if clean_subject:
            lines.extend(["", f"**Subject:** {clean_subject}"])
        
        # Add message content
        if body_without_images.strip():
            lines.extend(["", "📝 Message", body_without_images.strip()])
        
        # Add poster image
        poster_url = self._get_poster_url(images, context.title, body_without_images)
        if poster_url:
            lines.extend(["", f"![poster]({poster_url})"])
        
        extras = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": f"Jarvis Prime: {clean_subject}" if clean_subject else "Jarvis Prime",
            "jarvis::beautified": True,
            "jarvis::handler": "standard",
            "jarvis::allImageUrls": images or ([poster_url] if poster_url else [])
        }
        
        if images or poster_url:
            extras["client::notification"] = {"bigImageUrl": images[0] if images else poster_url}
        
        return ProcessingResult(
            text="\n".join(lines),
            extras=extras,
            images=images or ([poster_url] if poster_url else [])
        )
    
    def _get_severity_badge(self, title: str, body: str) -> str:
        """Determine severity badge from content"""
        text = f"{title} {body}".lower()
        if re.search(r'\b(error|failed|critical)\b', text):
            return "❌"
        elif re.search(r'\b(warn|warning)\b', text):
            return "⚠️"
        elif re.search(r'\b(success|ok|online|completed|pass|finished)\b', text):
            return "✅"
        return ""
    
    def _clean_subject(self, title: str, body: str) -> str:
        """Clean and normalize the subject line"""
        cleaned = (title or "").strip()
        
        # Remove intake prefixes
        intake_pattern = re.compile(r'^\s*(?:smtp|proxy|gotify|ntfy|apprise|webhooks?)\s*[:\-]?\s*', re.I)
        cleaned = intake_pattern.sub('', cleaned)
        
        # Remove Jarvis Prime prefixes
        jarvis_pattern = re.compile(r'^\s*(?:jarvis\s*prime\s*:?\s*)+', re.I)
        cleaned = jarvis_pattern.sub('', cleaned)
        
        return cleaned.strip()
    
    @lru_cache(maxsize=64)
    def _get_poster_url(self, images_tuple: Tuple[str, ...], title: str, body: str) -> Optional[str]:
        """Get poster URL with caching"""
        images = list(images_tuple) if images_tuple else []
        
        if images:
            return images[0]
        
        # Icon mapping for common services
        icon_map = {
            "sonarr": "https://raw.githubusercontent.com/walkxcode/dashboard-icons/master/png/sonarr.png",
            "radarr": "https://raw.githubusercontent.com/walkxcode/dashboard-icons/master/png/radarr.png",
            "watchtower": "https://raw.githubusercontent.com/walkxcode/dashboard-icons/master/png/watchtower.png",
            # Add more as needed
        }
        
        text = f"{title} {body}".lower()
        for service, icon_url in icon_map.items():
            if service in text:
                return icon_url
        
        return None

# -------- Main Processor --------
class MessageBeautifier:
    """Main message processing orchestrator"""
    
    def __init__(self):
        self.handlers: List[MessageHandler] = [
            WatchtowerHandler(),
            StandardHandler()  # Keep as last (default handler)
        ]
        self.processor = TextProcessor()
    
    def beautify_message(self, title: str, body: str, **kwargs) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Main entry point for message beautification"""
        try:
            # Early exit for disabled beautification
            if not config.beautify_enabled:
                return self._raw_passthrough(title, body, kwargs.get('persona'))
            
            # Handle special cases
            if self._is_joke_message(title):
                return self._handle_joke_message(title, body)
            
            if self._is_raw_persona_message(kwargs.get('extras_in')):
                return self._handle_raw_persona_message(title, body)
            
            # Create processing context
            context = MessageContext(
                title=title or "",
                body=body or "",
                source_hint=kwargs.get('source_hint'),
                persona=kwargs.get('persona'),
                extras_in=kwargs.get('extras_in'),
                mood=kwargs.get('mood', 'neutral'),
                mode=kwargs.get('mode', 'standard'),
                persona_quip=kwargs.get('persona_quip', True)
            )
            
            # Find appropriate handler
            handler = self._find_handler(context)
            if not handler:
                logger.warning("No handler found for message")
                return self._raw_passthrough(title, body, context.persona)
            
            # Process message
            result = handler.process(context)
            
            # Apply post-processing
            result = self._apply_post_processing(result, context)
            
            return result.text, result.extras
            
        except Exception as e:
            logger.error(f"Error beautifying message: {e}")
            return self._raw_passthrough(title, body, kwargs.get('persona'))
    
    def _find_handler(self, context: MessageContext) -> Optional[MessageHandler]:
        """Find the first handler that can process the message"""
        for handler in self.handlers:
            if handler.can_handle(context):
                return handler
        return None
    
    def _apply_post_processing(self, result: ProcessingResult, context: MessageContext) -> ProcessingResult:
        """Apply common post-processing steps"""
        # Add persona riffs if enabled
        if config.llm_riffs_enabled and context.persona:
            riffs = self._generate_persona_riffs(result.text, context.persona)
            if riffs:
                riff_lines = [f"", f"🧠 {context.persona} riff"]
                riff_lines.extend(f"> {riff}" for riff in riffs)
                result.text += "\n".join(riff_lines)
                result.extras["jarvis::llm_riff_lines"] = len(riffs)
        
        # Apply safe truncation
        result.text = self.processor.safe_truncate(result.text, config.max_message_length)
        
        return result
    
    def _generate_persona_riffs(self, context: str, persona: str) -> List[str]:
        """Generate persona-based commentary"""
        try:
            llm = importlib.import_module("llm_client")
            llm = importlib.reload(llm)
            
            riffs = llm.persona_riff(persona=persona, context=context)
            if isinstance(riffs, list):
                return [str(riff).strip() for riff in riffs if str(riff).strip()]
            elif isinstance(riffs, str) and riffs.strip():
                return [riffs.strip()]
        except Exception as e:
            logger.warning(f"Failed to generate persona riffs: {e}")
        
        return []
    
    def _is_joke_message(self, title: str) -> bool:
        """Check if message is a joke"""
        return isinstance(title, str) and "joke" in title.lower()
    
    def _is_raw_persona_message(self, extras_in: Optional[Dict[str, Any]]) -> bool:
        """Check if message should bypass persona processing"""
        return isinstance(extras_in, dict) and extras_in.get("jarvis::raw_persona")
    
    def _handle_joke_message(self, title: str, body: str) -> Tuple[str, Dict[str, Any]]:
        """Handle joke messages with minimal processing"""
        extras = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": title.strip() or "Jarvis Prime: Joke",
            "jarvis::beautified": False,
            "jarvis::raw_joke": True,
            "riff_hint": False,
        }
        return (body or "").strip(), extras
    
    def _handle_raw_persona_message(self, title: str, body: str) -> Tuple[str, Dict[str, Any]]:
        """Handle raw persona messages"""
        extras = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": f"Jarvis Prime: {(title or '').strip()}",
            "jarvis::beautified": False,
            "jarvis::raw_persona": True,
        }
        return body or "", extras
    
    def _raw_passthrough(self, title: str, body: str, persona: Optional[str]) -> Tuple[str, Dict[str, Any]]:
        """Handle raw message passthrough"""
        text_lines = []
        
        # Add persona overlay if enabled
        if config.personality_enabled and persona:
            text_lines.append(f"💬 {persona} says:")
        
        text_lines.append(body or "")
        
        extras = {
            "client::display": {"contentType": "text/markdown"},
            "client::title": f"Jarvis Prime: {(title or '').strip()}",
            "jarvis::beautified": False
        }
        
        return "\n".join(text_lines), extras

# -------- Public API --------
_beautifier = MessageBeautifier()

def beautify_message(title: str, body: str, **kwargs) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Public API function for message beautification
    
    Args:
        title: Message title/subject
        body: Message body content
        **kwargs: Additional options (mood, source_hint, persona, etc.)
    
    Returns:
        Tuple of (formatted_text, extras_dict)
    """
    return _beautifier.beautify_message(title, body, **kwargs)