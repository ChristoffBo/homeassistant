# BEFORE
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: str | None = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True,
                     llm_used: bool = False) -> Tuple[str, Optional[dict]]:

# AFTER
def beautify_message(title: str, body: str, *, mood: str = "neutral",
                     source_hint: Optional[str] = None, mode: str = "standard",
                     persona: Optional[str] = None, persona_quip: bool = True,
                     llm_used: bool = False) -> Tuple[str, Optional[dict]]: