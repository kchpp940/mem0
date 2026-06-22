import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class DepInfo:
    provider: str
    category: str
    import_packages: List[str]
    extras: Optional[str]
    pip_packages: List[str]


_REGISTRY: Dict[str, DepInfo] = {}


def register(
    provider: str,
    category: str,
    import_packages: List[str],
    extras: Optional[str] = None,
    pip_packages: Optional[List[str]] = None,
) -> None:
    _REGISTRY[provider] = DepInfo(
        provider=provider,
        category=category,
        import_packages=import_packages,
        extras=extras,
        pip_packages=pip_packages or import_packages,
    )


def get_all_providers() -> Dict[str, DepInfo]:
    return dict(_REGISTRY)


def get_dep_info(provider: str) -> Optional[DepInfo]:
    return _REGISTRY.get(provider)


def _build_message(info: DepInfo) -> str:
    pip_cmd = " ".join(info.pip_packages)
    parts = [
        f"The '{info.provider}' {info.category} provider requires: {pip_cmd}.",
        f"Install with: pip install {pip_cmd}",
    ]
    if info.extras:
        parts.append(f"Or install all {info.category} providers: pip install 'mem0ai[{info.extras}]'")
    return " ".join(parts)


def make_import_error(provider: str) -> ImportError:
    info = _REGISTRY.get(provider)
    if info is None:
        return ImportError(f"Unknown provider: {provider}")
    return ImportError(_build_message(info))


# ── pyproject.toml extras parsing & validation ────────────────────────

_PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)")


def _normalize_pkg(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def _parse_pin(spec: str) -> str:
    m = _PIN_RE.match(spec.strip())
    if not m:
        raise ValueError(f"Cannot parse package spec: {spec!r}")
    return _normalize_pkg(m.group(1))


def load_pyproject_extras(pyproject_path: Optional[str] = None) -> Dict[str, List[str]]:
    if pyproject_path is None:
        pyproject_path = str(Path(__file__).resolve().parents[2] / "pyproject.toml")
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    raw = data.get("project", {}).get("optional-dependencies", {})
    result: Dict[str, List[str]] = {}
    for group, specs in raw.items():
        result[group] = sorted({_parse_pin(s) for s in specs})
    return result


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    provider: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.provider}: {self.message}"


def validate_registry(pyproject_path: Optional[str] = None) -> List[ValidationIssue]:
    extras_map = load_pyproject_extras(pyproject_path)
    issues: List[ValidationIssue] = []
    for provider, info in _REGISTRY.items():
        if info.extras is None:
            continue
        if info.extras not in extras_map:
            issues.append(
                ValidationIssue(
                    "error",
                    provider,
                    f"references extras group [{info.extras}] which does not exist in pyproject.toml",
                )
            )
            continue
        group_pkgs = set(extras_map[info.extras])
        missing = [pkg for pkg in info.pip_packages if _normalize_pkg(pkg) not in group_pkgs]
        if missing:
            issues.append(
                ValidationIssue(
                    "warning",
                    provider,
                    f"pip_packages {missing} not found in extras group [{info.extras}]",
                )
            )
    return issues


def validate_factory_dep_keys(mapping: Dict[str, str], category: str) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for factory_name, dep_key in mapping.items():
        info = _REGISTRY.get(dep_key)
        if info is None:
            issues.append(
                ValidationIssue(
                    "error",
                    factory_name,
                    f"factory '{category}' maps to unknown dep key '{dep_key}'",
                )
            )
            continue
        if info.category != category:
            issues.append(
                ValidationIssue(
                    "warning",
                    factory_name,
                    f"dep key '{dep_key}' has category '{info.category}' but factory category is '{category}'",
                )
            )
    return issues


# ── LLMs ──────────────────────────────────────────────────────────────
register("ollama",             "llm", ["ollama"],                       "llms",   ["ollama"])
register("groq",               "llm", ["groq"],                         "llms",   ["groq"])
register("together",           "llm", ["together"],                     "llms",   ["together"])
register("litellm",            "llm", ["litellm"],                      "llms",   ["litellm"])
register("anthropic",          "llm", ["anthropic"],                    "llms",   ["anthropic"])
register("gemini",             "llm", ["google.genai"],                 "llms",   ["google-genai"])
register("aws_bedrock",        "llm", ["boto3"],                        "extras", ["boto3"])
register("langchain",          "llm", ["langchain.chat_models.base", "langchain_core.messages"], "extras", ["langchain", "langchain-core"])

# ── Embeddings ────────────────────────────────────────────────────────
register("ollama_emb",         "embedding", ["ollama"],                 "llms",   ["ollama"])
register("huggingface",        "embedding", ["sentence_transformers"],  "extras", ["sentence-transformers"])
register("azure_openai_emb",   "embedding", ["azure.identity", "openai"], "extras", ["azure-identity"])
register("gemini_emb",         "embedding", ["google.genai"],           "llms",   ["google-genai"])
register("vertexai_emb",       "embedding", ["vertexai"],               "llms",   ["vertexai"])
register("together_emb",       "embedding", ["together"],               "llms",   ["together"])
register("aws_bedrock_emb",    "embedding", ["boto3"],                  "extras", ["boto3"])
register("fastembed",          "embedding", ["fastembed"],              "extras", ["fastembed"])
register("langchain_emb",      "embedding", ["langchain.embeddings.base"], "extras", ["langchain"])

# ── Vector stores ─────────────────────────────────────────────────────
register("chroma",             "vector_store", ["chromadb"],            "vector-stores", ["chromadb"])
register("pgvector",           "vector_store", ["psycopg"],             "vector-stores", ["psycopg", "psycopg-pool"])
register("milvus",             "vector_store", ["pymilvus"],            "vector-stores", ["pymilvus"])
register("upstash_vector",     "vector_store", ["upstash_vector"],      "vector-stores", ["upstash-vector"])
register("pinecone",           "vector_store", ["pinecone"],            "vector-stores", ["pinecone", "pinecone-text"])
register("weaviate",           "vector_store", ["weaviate"],            "vector-stores", ["weaviate-client"])
register("qdrant_extra",       "vector_store", ["fastembed"],           "extras",  ["fastembed"])
register("supabase",           "vector_store", ["vecs"],                "vector-stores", ["vecs"])
register("azure_ai_search",    "vector_store", ["azure.search.documents"], "vector-stores", ["azure-search-documents", "azure-identity"])
register("azure_mysql",        "vector_store", ["pymysql", "dbutils", "azure.identity"], "vector-stores", ["pymysql", "dbutils", "azure-identity"])
register("mongodb",            "vector_store", ["pymongo"],             "vector-stores", ["pymongo"])
register("redis_vs",           "vector_store", ["redis", "redisvl"],    "vector-stores", ["redis", "redisvl"])
register("valkey_vs",          "vector_store", ["valkey"],              "vector-stores", ["valkey"])
register("elasticsearch_vs",   "vector_store", ["elasticsearch"],      "vector-stores", ["elasticsearch"])
register("opensearch",         "vector_store", ["opensearchpy"],        "extras",  ["opensearch-py"])
register("faiss",              "vector_store", ["faiss"],               "vector-stores", ["faiss-cpu"])
register("cassandra",          "vector_store", ["cassandra.cluster"],   "vector-stores", ["cassandra-driver"])
register("databricks",         "vector_store", ["databricks.sdk"],      "vector-stores", ["databricks-sdk"])
register("baidu",              "vector_store", ["pymochow"],            "vector-stores", ["pymochow"])
register("neptune",            "vector_store", ["langchain_aws"],       "vector-stores", ["langchain-aws"])
register("turbopuffer",        "vector_store", ["turbopuffer"],         "vector-stores", ["turbopuffer"])
register("s3_vectors",         "vector_store", ["boto3"],               "extras",  ["boto3"])
register("langchain_vs",       "vector_store", ["langchain_community.vectorstores"], "extras", ["langchain-community"])
register("vertex_ai_vector_search", "vector_store", ["vertexai"],      "llms",    ["vertexai"])

# ── Rerankers ─────────────────────────────────────────────────────────
register("cohere_reranker",       "reranker", ["cohere"],               "extras",  ["cohere"])
register("sentence_transformer",  "reranker", ["sentence_transformers"], "extras",  ["sentence-transformers"])
register("huggingface_reranker",  "reranker", ["transformers", "torch"], None,      ["transformers", "torch"])
register("zero_entropy",          "reranker", ["zeroentropy"],          None,      ["zeroentropy"])

# ── Extras / cross-cutting ────────────────────────────────────────────
register("spacy",              "nlp",  ["spacy"],                       "nlp",    ["spacy"])
