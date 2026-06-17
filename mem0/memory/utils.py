import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from mem0.configs.prompts import (
    AGENT_MEMORY_EXTRACTION_PROMPT,
    FACT_RETRIEVAL_PROMPT,
    USER_MEMORY_EXTRACTION_PROMPT,
)

logger = logging.getLogger(__name__)


@dataclass
class NormalizedMessage:
    """Structured representation of a validated chat message.

    Used as the single source of truth across raw add (infer=False), LLM
    extraction (infer=True), metadata merging, history persistence, and
    return-value building so that role / name / actor_id / content stay
    consistent through every branch.
    """

    index: int = 0
    role: Optional[str] = None
    content: Optional[str] = None
    name: Optional[str] = None
    actor_id: Optional[str] = None
    valid: bool = False
    skip_reason: Optional[str] = None
    original: Dict[str, Any] = field(default_factory=dict)


def normalize_messages(messages):
    """Validate and normalize a batch of chat messages into structured records.

    Each input message is independently inspected.  Invalid entries (wrong
    type, missing role/content, system role, no textual content) are marked
    with ``valid=False`` and a ``skip_reason`` -- the caller can then log /
    skip them without affecting siblings.

    Each record preserves its original ``index`` in the input list so the
    LLM's ``source_index`` references can be validated and mapped back.

    Returns a list of ``NormalizedMessage`` objects, one per input message.
    """
    normalized = []
    for idx, msg in enumerate(messages):
        record = NormalizedMessage()
        record.index = idx

        if not isinstance(msg, dict):
            record.skip_reason = "not a dict at all"
            normalized.append(record)
            continue

        record.original = dict(msg)
        role = msg.get("role")
        content = msg.get("content")
        name = msg.get("name")

        if role is None:
            record.skip_reason = "missing role"
            normalized.append(record)
            continue

        if content is None:
            record.skip_reason = "missing content"
            normalized.append(record)
            continue

        if role == "system":
            record.skip_reason = "system role skipped"
            normalized.append(record)
            continue

        record.role = role
        record.content = content
        record.name = name
        record.actor_id = name if name else None
        record.valid = True
        normalized.append(record)

    return normalized


def get_fact_retrieval_messages(message, is_agent_memory=False):
    """Get fact retrieval messages based on the memory type.
    
    Args:
        message: The message content to extract facts from
        is_agent_memory: If True, use agent memory extraction prompt, else use user memory extraction prompt
        
    Returns:
        tuple: (system_prompt, user_prompt)
    """
    if is_agent_memory:
        return AGENT_MEMORY_EXTRACTION_PROMPT, f"Input:\n{message}"
    else:
        return USER_MEMORY_EXTRACTION_PROMPT, f"Input:\n{message}"


def get_fact_retrieval_messages_legacy(message):
    """Legacy function for backward compatibility."""
    return FACT_RETRIEVAL_PROMPT, f"Input:\n{message}"


def ensure_json_instruction(system_prompt, user_prompt):
    """Ensure the word 'json' appears in the prompts when using json_object response format.

    OpenAI's API requires the word 'json' to appear in the messages when
    response_format is set to {"type": "json_object"}. When users provide a
    custom_instructions that doesn't include 'json', this causes a
    400 error. This function appends a JSON format instruction to the system
    prompt if 'json' is not already present in either prompt.

    Args:
        system_prompt: The system prompt string
        user_prompt: The user prompt string

    Returns:
        tuple: (system_prompt, user_prompt) with JSON instruction added if needed
    """
    combined = (system_prompt + user_prompt).lower()
    if "json" not in combined:
        system_prompt += (
            "\n\nYou must return your response in valid JSON format "
            "with a 'facts' key containing an array of strings."
        )
    return system_prompt, user_prompt


def parse_messages(messages, include_indices=False):
    """Render a batch of chat messages into a single text block.

    Accepts either raw message dicts or pre-normalized ``NormalizedMessage``
    objects so both the infer=False and infer=True paths can share this.
    Messages with a ``name`` are rendered as ``role (name): content`` so the
    LLM can see the actor identity alongside the role.

    When ``include_indices=True``, each valid message is prefixed with
    ``mN:`` where N is the message's original list index.  This is used for
    the extraction prompt so the LLM can return ``source_index`` fields
    that map deterministically back to specific input messages.
    """
    response = ""
    for msg in messages:
        if isinstance(msg, NormalizedMessage):
            if not msg.valid:
                continue
            role = msg.role
            content = msg.content
            name = msg.name
            msg_index = msg.index
        elif isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content")
            name = msg.get("name")
            if content is None or role is None or role == "system":
                continue
            msg_index = msg.get("index", 0)
        else:
            continue

        if name:
            prefix = f"{role} ({name})"
        else:
            prefix = role

        if include_indices:
            response += f"m{msg_index}: {prefix}: {content}\n"
        else:
            response += f"{prefix}: {content}\n"
    return response


def build_actor_mapping(normalized_messages):
    """Build a role -> actor_id map from normalized messages.

    When the LLM only returns ``attributed_to: "user"`` or ``"assistant"`` we
    can look up the real ``actor_id`` (from the original message's ``name``
    field) using this mapping.  The first valid message per role wins, which
    is consistent with how most chat apps treat identity within a turn.
    """
    mapping: Dict[str, Optional[str]] = {}
    for nm in normalized_messages:
        if not nm.valid:
            continue
        if nm.role and nm.role not in mapping:
            mapping[nm.role] = nm.actor_id
    return mapping


def build_source_actor_records(normalized_messages):
    """Return unique (role, actor_id, name) tuples from valid messages.

    Stored in history payloads so the original actor attribution is fully
    traceable even when the LLM extraction only emits a coarse ``attributed_to``
    value.
    """
    seen = set()
    records = []
    for nm in normalized_messages:
        if not nm.valid:
            continue
        key = (nm.role, nm.actor_id, nm.name)
        if key in seen:
            continue
        seen.add(key)
        records.append({"role": nm.role, "actor_id": nm.actor_id, "name": nm.name})
    return records


@dataclass
class ActorIndexEntry:
    """A single message's actor context, used for resolving extraction attributions."""

    index: int
    role: str
    name: Optional[str]
    actor_id: Optional[str]
    content: str
    content_lower: str = field(init=False)

    def __post_init__(self):
        self.content_lower = (self.content or "").lower()


@dataclass
class ActorIndex:
    """Index of all valid messages for multi-actor attribution resolution.

    Preserves the full list of messages in original order, with side indexes
    for fast lookups by role and by name.  Used by :func:`resolve_actor` to
    map LLM-extracted facts back to specific source messages rather than
    assuming one actor per role.
    """

    entries: List[ActorIndexEntry] = field(default_factory=list)
    by_role: Dict[str, List[ActorIndexEntry]] = field(default_factory=dict)
    by_name: Dict[str, List[ActorIndexEntry]] = field(default_factory=dict)

    def unique_actors_for_role(self, role: str) -> List[Optional[str]]:
        """Return distinct actor_ids for a given role (preserves None if present)."""
        seen = set()
        result = []
        for entry in self.by_role.get(role, []):
            if entry.actor_id not in seen:
                seen.add(entry.actor_id)
                result.append(entry.actor_id)
        return result


def build_actor_index(normalized_messages: List[NormalizedMessage]) -> ActorIndex:
    """Build an ActorIndex from normalized messages for multi-actor resolution.

    Only valid messages are indexed.  The index preserves original message
    order and builds side lookup tables by role and by name.
    """
    index = ActorIndex()
    for idx, nm in enumerate(normalized_messages):
        if not nm.valid or not nm.role or not nm.content:
            continue
        entry = ActorIndexEntry(
            index=idx,
            role=nm.role,
            name=nm.name,
            actor_id=nm.actor_id,
            content=nm.content,
        )
        index.entries.append(entry)
        index.by_role.setdefault(nm.role, []).append(entry)
        if nm.name:
            index.by_name.setdefault(nm.name, []).append(entry)
    return index


def resolve_actor(
    extracted_memory: Dict[str, Any],
    actor_index: ActorIndex,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve actor_id and role for an LLM-extracted memory.

    Matches in priority order:

    1. **Exact name match**: if the extraction includes ``name`` and there is
       exactly one unique actor_id for that name, return it.
    2. **Content binding**: if the extracted ``text`` is clearly derived from
       a specific message (the message content is a substring of the memory,
       or vice versa, ignoring case), use that message's actor.
    3. **Unique role match**: if the extraction includes ``attributed_to`` and
       there is exactly one unique actor_id for that role across all messages,
       return it.
    4. **Ambiguous**: if none of the above produce a unique match, return
       ``(None, role, None)`` so the caller can still store the coarse role
       and source_actors without guessing the wrong actor_id.

    Args:
        extracted_memory: The LLM-extracted memory dict (keys: text, attributed_to, name, role).
        actor_index: The ActorIndex built from the original normalized messages.

    Returns:
        Tuple of ``(actor_id, role, match_reason)`` where ``match_reason`` is
        a short string describing which rule fired, or ``None`` if ambiguous.
    """
    mem_text = (extracted_memory.get("text") or "").lower()
    mem_name = extracted_memory.get("name")
    mem_attributed_to = extracted_memory.get("attributed_to")
    mem_role = extracted_memory.get("role") or mem_attributed_to

    # ---- Priority 1: exact name match ---------------------------------------
    if mem_name:
        name_entries = actor_index.by_name.get(mem_name, [])
        unique_actors = list({e.actor_id for e in name_entries})
        if len(unique_actors) == 1 and unique_actors[0] is not None:
            # Resolve role from the entry as well
            entry_role = name_entries[0].role
            return unique_actors[0], entry_role, "name_match"
        if len(unique_actors) > 1:
            # Same name but different actor_ids - ambiguous, don't guess
            return None, mem_role, None

    # ---- Priority 2: content binding ----------------------------------------
    if mem_text:
        candidates = []
        for entry in actor_index.entries:
            if not entry.content_lower:
                continue
            # Check if message content is contained in the memory text, or
            # the memory text is contained in the message (substantial overlap)
            if entry.content_lower in mem_text or mem_text in entry.content_lower:
                candidates.append(entry)
        if len(candidates) == 1:
            return candidates[0].actor_id, candidates[0].role, "content_match"
        if len(candidates) > 1:
            # Multiple messages match - check if they all share the same actor
            shared_actors = list({e.actor_id for e in candidates})
            shared_roles = list({e.role for e in candidates})
            if len(shared_actors) == 1 and shared_actors[0] is not None:
                return shared_actors[0], shared_roles[0], "content_match_shared_actor"

    # ---- Priority 3: unique role match --------------------------------------
    if mem_attributed_to:
        unique_actors = actor_index.unique_actors_for_role(mem_attributed_to)
        if len(unique_actors) == 1 and unique_actors[0] is not None:
            return unique_actors[0], mem_attributed_to, "unique_role_match"
        # If multiple actors for this role, fall through to ambiguous

    # ---- Ambiguous: return raw role without guessing actor_id ---------------
    return None, mem_role, None


@dataclass
class ResolvedSource:
    """Result of validating an LLM extraction's source fields against normalized messages.

    Attributes:
        actor_id: The validated actor_id from the source message, or None if no valid source.
        role: The validated role from the source message, or attributed_to fallback.
        source_index: The original message index if valid, or None.
        source_name: The validated source name if provided and matches, or None.
        valid: Whether at least one source field validated successfully.
        validation_reason: Short string describing which rule fired or why it failed.
    """

    actor_id: Optional[str] = None
    role: Optional[str] = None
    source_index: Optional[int] = None
    source_name: Optional[str] = None
    valid: bool = False
    validation_reason: Optional[str] = None


def validate_extraction_sources(
    extracted_memory: Dict[str, Any],
    normalized_messages: List[NormalizedMessage],
    actor_index: ActorIndex,
) -> ResolvedSource:
    """Validate LLM-extracted source fields (source_index, source_name, attributed_to).

    Only accepts source references that actually exist in the original normalized
    messages.  Invalid references (out-of-range index, mismatched name, unknown
    role) are silently discarded -- the function still returns a best-effort
    ResolvedSource but with ``valid=False`` so the caller can decide whether to
    skip the memory or store it without actor attribution.

    Validation priority (matching the prompt contract):

    1. **source_index + source_name**: If both are present, verify the message
       at that index has a matching name.
    2. **source_index only**: Verify the index points to a valid, non-skipped
       message.  The message's name becomes the source_name, its actor_id and
       role are used.
    3. **source_name only**: Verify the name exists in the message set.  If
       exactly one unique actor_id has that name, use it.
    4. **attributed_to fallback**: If none of the above, fall through to
       :func:`resolve_actor` for the existing best-effort heuristics.

    Args:
        extracted_memory: The LLM-returned memory dict (text, attributed_to, source_index, source_name).
        normalized_messages: Full list of normalized messages with their original indices.
        actor_index: Pre-built ActorIndex for fast name/role lookups.

    Returns:
        ResolvedSource with validated actor_id, role, and source references.
    """
    raw_source_index = extracted_memory.get("source_index")
    raw_source_name = extracted_memory.get("source_name")
    raw_attributed_to = extracted_memory.get("attributed_to")

    # Build a fast lookup by original message index (skipping invalid messages)
    by_index: Dict[int, NormalizedMessage] = {
        nm.index: nm for nm in normalized_messages if nm.valid
    }

    # ---- Priority 1: source_index + source_name -----------------------------
    if raw_source_index is not None and raw_source_name:
        try:
            idx = int(raw_source_index)
        except (TypeError, ValueError):
            pass
        else:
            nm = by_index.get(idx)
            if nm is not None and nm.name == raw_source_name:
                return ResolvedSource(
                    actor_id=nm.actor_id,
                    role=nm.role,
                    source_index=idx,
                    source_name=nm.name,
                    valid=True,
                    validation_reason="source_index_and_name_match",
                )
            # If index is valid but name doesn't match, it's a hallucination.
            # Do NOT fall through to source_index-only or heuristic matches --
            # the LLM explicitly gave a name that contradicts the source message.
            if nm is not None:
                return ResolvedSource(
                    actor_id=None,
                    role=raw_attributed_to,
                    source_index=idx,
                    source_name=raw_source_name,
                    valid=False,
                    validation_reason="source_name_mismatch_at_index",
                )
            # Index is invalid (out of range or skipped) - fall through to try name-only

    # ---- Priority 2: source_index only (only if no source_name was provided) -
    if raw_source_index is not None and raw_source_name is None:
        try:
            idx = int(raw_source_index)
        except (TypeError, ValueError):
            pass
        else:
            nm = by_index.get(idx)
            if nm is not None:
                return ResolvedSource(
                    actor_id=nm.actor_id,
                    role=nm.role,
                    source_index=idx,
                    source_name=nm.name,
                    valid=True,
                    validation_reason="source_index_match",
                )

    # ---- Priority 3: source_name only ---------------------------------------
    if raw_source_name:
        name_entries = actor_index.by_name.get(raw_source_name, [])
        unique_actors = list({e.actor_id for e in name_entries if e.actor_id is not None})
        if len(unique_actors) == 1:
            entry_role = name_entries[0].role if name_entries else raw_attributed_to
            return ResolvedSource(
                actor_id=unique_actors[0],
                role=entry_role,
                source_index=None,
                source_name=raw_source_name,
                valid=True,
                validation_reason="source_name_match",
            )
        if len(unique_actors) > 1:
            # Same name but multiple actor_ids - ambiguous, don't guess
            return ResolvedSource(
                actor_id=None,
                role=raw_attributed_to,
                source_index=None,
                source_name=raw_source_name,
                valid=False,
                validation_reason="source_name_ambiguous_multiple_actors",
            )

    # ---- Priority 4: attributed_to + heuristics fallback --------------------
    # Only fall back to content/role heuristics when the LLM did NOT provide
    # explicit source_index or source_name fields. If it did provide them but
    # they didn't validate, we already returned a failed ResolvedSource above.
    if raw_source_index is None and raw_source_name is None:
        resolved_actor_id, resolved_role, heuristic_reason = resolve_actor(extracted_memory, actor_index)
        if resolved_actor_id is not None:
            return ResolvedSource(
                actor_id=resolved_actor_id,
                role=resolved_role or raw_attributed_to,
                source_index=None,
                source_name=None,
                valid=True,
                validation_reason=f"heuristic_fallback:{heuristic_reason}",
            )

    # ---- No valid source found ----------------------------------------------
    return ResolvedSource(
        actor_id=None,
        role=raw_attributed_to,
        source_index=None if not isinstance(raw_source_index, int) else raw_source_index,
        source_name=raw_source_name,
        valid=False,
        validation_reason="no_valid_source",
    )


def format_entities(entities):
    if not entities:
        return ""

    formatted_lines = []
    for entity in entities:
        simplified = f"{entity['source']} -- {entity['relationship']} -- {entity['destination']}"
        formatted_lines.append(simplified)

    return "\n".join(formatted_lines)

def normalize_facts(raw_facts):
    """Normalize LLM-extracted facts to a list of strings.

    Smaller LLMs (e.g. llama3.1:8b) sometimes return facts as objects
    like {"fact": "..."} or {"text": "..."} instead of plain strings.
    This mirrors the TypeScript FactRetrievalSchema validation.
    """
    if not raw_facts:
        return []
    normalized = []
    for item in raw_facts:
        if isinstance(item, str):
            fact = item
        elif isinstance(item, dict):
            fact = item.get("fact") or item.get("text")
            if fact is None:
                logger.warning("Unexpected fact shape from LLM, skipping: %s", item)
                continue
        else:
            fact = str(item)
        if fact:
            normalized.append(fact)
    return normalized


def remove_code_blocks(content: str) -> str:
    """
    Removes enclosing code block markers ```[language] and ``` from a given string.

    Remarks:
    - The function uses a regex pattern to match code blocks that may start with ``` followed by an optional language tag (letters or numbers) and end with ```.
    - If a code block is detected, it returns only the inner content, stripping out the markers.
    - If no code block markers are found, the original content is returned as-is.
    """
    pattern = r"^```[a-zA-Z0-9]*\n([\s\S]*?)\n```$"
    match = re.match(pattern, content.strip())
    match_res=match.group(1).strip() if match else content.strip()
    return re.sub(r"<think>.*?</think>", "", match_res, flags=re.DOTALL).strip()



def extract_json(text):
    """
    Extracts JSON content from a string, removing enclosing triple backticks and optional 'json' tag if present.
    If no code block is found, attempts to locate JSON by finding the first '{' and last '}'.
    If that also fails, returns the text as-is.
    """
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = text[start_idx : end_idx + 1]
        else:
            json_str = text
    return json_str


def get_image_description(image_obj, llm, vision_details):
    """
    Get the description of the image
    """

    if isinstance(image_obj, str):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "A user is providing an image. Provide a high level description of the image and do not include any additional text.",
                    },
                    {"type": "image_url", "image_url": {"url": image_obj, "detail": vision_details}},
                ],
            },
        ]
    else:
        messages = [image_obj]

    response = llm.generate_response(messages=messages)
    return response


def parse_vision_messages(messages, llm=None, vision_details="auto"):
    """
    Parse the vision messages from the messages
    """
    returned_messages = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            returned_messages.append(msg)
            continue

        # Skip messages without content (e.g. assistant tool-call messages
        # that carry `tool_calls` but no `content` key).
        if content is None:
            continue

        # Handle message content
        if isinstance(content, list):
            if llm is None:
                text_parts = [
                    part["text"] for part in msg["content"]
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                if not text_parts:
                    continue
                returned_messages.append({"role": role, "content": " ".join(text_parts)})
            else:
                description = get_image_description(msg, llm, vision_details)
                returned_messages.append({"role": role, "content": description})
        elif isinstance(content, dict) and content.get("type") == "image_url":
            if llm is None:
                continue
            image_url = content["image_url"]["url"]
            try:
                description = get_image_description(image_url, llm, vision_details)
                returned_messages.append({"role": role, "content": description})
            except Exception:
                raise Exception(f"Error while downloading {image_url}.")
        else:
            # Regular text content
            returned_messages.append(msg)

    return returned_messages


def process_telemetry_filters(filters):
    """
    Process the telemetry filters
    """
    if filters is None:
        return {}

    encoded_ids = {}
    if "user_id" in filters:
        encoded_ids["user_id"] = hashlib.md5(filters["user_id"].encode()).hexdigest()
    if "agent_id" in filters:
        encoded_ids["agent_id"] = hashlib.md5(filters["agent_id"].encode()).hexdigest()
    if "run_id" in filters:
        encoded_ids["run_id"] = hashlib.md5(filters["run_id"].encode()).hexdigest()

    return list(filters.keys()), encoded_ids


def sanitize_relationship_for_cypher(relationship) -> str:
    """Sanitize relationship text for Cypher queries by replacing problematic characters."""
    char_map = {
        "...": "_ellipsis_",
        "…": "_ellipsis_",
        "。": "_period_",
        "，": "_comma_",
        "；": "_semicolon_",
        "：": "_colon_",
        "！": "_exclamation_",
        "？": "_question_",
        "（": "_lparen_",
        "）": "_rparen_",
        "【": "_lbracket_",
        "】": "_rbracket_",
        "《": "_langle_",
        "》": "_rangle_",
        "'": "_apostrophe_",
        '"': "_quote_",
        "\\": "_backslash_",
        "/": "_slash_",
        "|": "_pipe_",
        "&": "_ampersand_",
        "=": "_equals_",
        "+": "_plus_",
        "*": "_asterisk_",
        "^": "_caret_",
        "%": "_percent_",
        "$": "_dollar_",
        "#": "_hash_",
        "@": "_at_",
        "!": "_bang_",
        "?": "_question_",
        "(": "_lparen_",
        ")": "_rparen_",
        "[": "_lbracket_",
        "]": "_rbracket_",
        "{": "_lbrace_",
        "}": "_rbrace_",
        "<": "_langle_",
        ">": "_rangle_",
        "-": "_",
    }

    # Apply replacements and clean up
    sanitized = relationship
    for old, new in char_map.items():
        sanitized = sanitized.replace(old, new)

    return re.sub(r"_+", "_", sanitized).strip("_")


def remove_spaces_from_entities(
    entity_list: List[Any],
    *,
    sanitize_relationship: bool = True,
) -> List[Dict[str, Any]]:
    """
    Normalize entity relation dicts from LLM/tool output: lowercase, spaces to underscores.

    Skips entries that are not non-empty dicts or that lack any of
    ``source``, ``relationship``, or ``destination`` (avoids KeyError on ``[{}]``
    or partial dicts).
    """
    required = ("source", "relationship", "destination")
    cleaned: List[Dict[str, Any]] = []
    for item in entity_list:
        if not isinstance(item, dict) or not item:
            continue
        if not all(key in item for key in required):
            continue
        item["source"] = item["source"].lower().replace(" ", "_")
        rel = item["relationship"].lower().replace(" ", "_")
        item["relationship"] = sanitize_relationship_for_cypher(rel) if sanitize_relationship else rel
        item["destination"] = item["destination"].lower().replace(" ", "_")
        cleaned.append(item)
    return cleaned

