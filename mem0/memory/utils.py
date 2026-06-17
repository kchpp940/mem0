import hashlib
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from mem0.configs.prompts import (
    AGENT_MEMORY_EXTRACTION_PROMPT,
    FACT_RETRIEVAL_PROMPT,
    USER_MEMORY_EXTRACTION_PROMPT,
)
from mem0.utils.scoring import PoolStatus

logger = logging.getLogger(__name__)


def _get_payload(mem: Any) -> Dict[str, Any]:
    """Extract payload from a vector store result object."""
    if hasattr(mem, "payload"):
        return mem.payload or {}
    if isinstance(mem, dict):
        return mem.get("payload", {})
    return {}


def _get_id(mem: Any) -> Optional[str]:
    """Extract id from a vector store result object."""
    if hasattr(mem, "id"):
        return str(mem.id)
    if isinstance(mem, dict):
        mem_id = mem.get("id")
        return str(mem_id) if mem_id is not None else None
    return None


def _get_score(mem: Any) -> float:
    """Extract score from a vector store result object."""
    if hasattr(mem, "score"):
        return mem.score or 0.0
    if isinstance(mem, dict):
        return mem.get("score") or 0.0
    return 0.0


def build_candidate_pool(
    semantic_results: Optional[List[Any]],
    keyword_candidates: Dict[str, Dict[str, Any]],
    entity_boosts: Dict[str, float],
    vector_store_get: Optional[Callable[[str], Any]],
    precomputed_entity_payloads: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], PoolStatus]:
    """Build a unified candidate pool from semantic, keyword, and entity lanes.

    This helper merges results from up to three retrieval lanes, de-duplicates
    by memory id, tracks which lanes contributed to each candidate, and fills
    in missing payloads for entity-only hits via ``vector_store_get`` or
    ``precomputed_entity_payloads``.

    Each candidate in the returned list has:
    - ``id``: memory id (str)
    - ``score``: semantic score, or 0.0 for keyword-only / entity-only hits
    - ``payload``: memory payload dict
    - ``sources``: list of lane names that produced this candidate
      (``"semantic"``, ``"keyword"``, ``"entity"``)

    The ``pool_status`` dict records:
    - ``semantic_ok``: whether the semantic lane returned results
    - ``keyword_ok``: whether the keyword lane returned results
    - ``entity_ok``: whether the entity boost lane returned any hits
    - ``degraded``: true if semantic lane failed but other lanes produced hits
    - ``degradation_reason``: human-readable reason when degraded

    If the semantic lane failed (``semantic_results is None``) but other
    lanes have candidates, ``pool_status.degraded`` is ``True`` so that
    downstream code can surface this information to the caller (e.g. via
    ``explain`` fields) rather than silently pretending it was a normal
    hybrid search.

    Args:
        semantic_results: Results from semantic search, or None if the
            semantic lane failed entirely.
        keyword_candidates: Mapping from memory id to payload for results
            from keyword search.
        entity_boosts: Mapping from memory id to entity boost score.
        vector_store_get: Callable that fetches a memory record by id.
            Used to fill payloads for candidates that only appear in the
            entity boost lane.  Ignored if ``precomputed_entity_payloads``
            is provided.
        precomputed_entity_payloads: Optional pre-fetched payloads for
            entity-only candidates, keyed by memory id.  When provided,
            ``vector_store_get`` is not called for entity-only hits.
            This is useful for async callers that want to fetch payloads
            asynchronously before calling this sync helper.

    Returns:
        Tuple of (candidates list, pool_status dict).
    """
    pool_status: PoolStatus = {
        "semantic_ok": semantic_results is not None,
        "keyword_ok": bool(keyword_candidates),
        "entity_ok": bool(entity_boosts),
        "degraded": False,
    }

    seen: Dict[str, Dict[str, Any]] = {}

    if semantic_results is not None:
        for mem in semantic_results:
            mem_id = _get_id(mem)
            if mem_id is None:
                continue
            seen[mem_id] = {
                "id": mem_id,
                "score": _get_score(mem),
                "payload": _get_payload(mem),
                "sources": ["semantic"],
            }

    for mem_id, payload in keyword_candidates.items():
        if mem_id in seen:
            seen[mem_id]["sources"].append("keyword")
        else:
            seen[mem_id] = {
                "id": mem_id,
                "score": 0.0,
                "payload": payload,
                "sources": ["keyword"],
            }

    entity_only_ids = [mem_id for mem_id in entity_boosts if mem_id not in seen]
    for mem_id in entity_boosts:
        if mem_id in seen:
            if "entity" not in seen[mem_id]["sources"]:
                seen[mem_id]["sources"].append("entity")

    if entity_only_ids:
        if precomputed_entity_payloads is not None:
            for mem_id in entity_only_ids:
                payload = precomputed_entity_payloads.get(mem_id)
                if payload:
                    seen[mem_id] = {
                        "id": mem_id,
                        "score": 0.0,
                        "payload": payload,
                        "sources": ["entity"],
                    }
        elif vector_store_get is not None:
            try:
                for mem_id in entity_only_ids:
                    result = vector_store_get(mem_id)
                    if result is not None:
                        payload = _get_payload(result)
                        if not payload and isinstance(result, dict):
                            payload = result
                        seen[mem_id] = {
                            "id": mem_id,
                            "score": 0.0,
                            "payload": payload,
                            "sources": ["entity"],
                        }
            except Exception as e:
                logger.warning(
                    "Failed to fetch payloads for entity-only candidates: %s",
                    e,
                )

    if not pool_status["semantic_ok"] and (pool_status["keyword_ok"] or pool_status["entity_ok"]):
        pool_status["degraded"] = True
        pool_status["degradation_reason"] = "Semantic search failed; results from keyword/entity lanes only"

    return list(seen.values()), pool_status


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
            "\n\nYou must return your response in valid JSON format with a 'facts' key containing an array of strings."
        )
    return system_prompt, user_prompt


def parse_messages(messages):
    response = ""
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        # Skip messages without textual content (e.g. assistant tool-call
        # messages that carry `tool_calls` but no `content` key).
        if content is None:
            continue
        if role == "system":
            response += f"system: {content}\n"
        elif role == "user":
            response += f"user: {content}\n"
        elif role == "assistant":
            response += f"assistant: {content}\n"
    return response


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
    match_res = match.group(1).strip() if match else content.strip()
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
                    part["text"] for part in msg["content"] if isinstance(part, dict) and part.get("type") == "text"
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
