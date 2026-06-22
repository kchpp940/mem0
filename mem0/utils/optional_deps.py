import re
import sys
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
    factory_name: Optional[str]


_REGISTRY: Dict[str, DepInfo] = {}


def register(
    provider: str,
    category: str,
    import_packages: List[str],
    extras: Optional[str] = None,
    pip_packages: Optional[List[str]] = None,
    factory_name: Optional[str] = None,
) -> None:
    _REGISTRY[provider] = DepInfo(
        provider=provider,
        category=category,
        import_packages=import_packages,
        extras=extras,
        pip_packages=pip_packages or import_packages,
        factory_name=factory_name,
    )


def get_all_providers() -> Dict[str, DepInfo]:
    return dict(_REGISTRY)


def get_dep_info(provider: str) -> Optional[DepInfo]:
    return _REGISTRY.get(provider)


def build_factory_dep_keys() -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for dep_key, info in _REGISTRY.items():
        if info.factory_name is None:
            continue
        result.setdefault(info.category, {})[info.factory_name] = dep_key
    return result


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
        if info.extras is not None and info.extras not in extras_map:
            issues.append(
                ValidationIssue(
                    "error",
                    provider,
                    f"references extras group [{info.extras}] which does not exist in pyproject.toml",
                )
            )
            continue
        if info.extras is not None:
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


def validate_factory_dep_keys(factory_dep_keys: Dict[str, Dict[str, str]]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for category, mapping in factory_dep_keys.items():
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


def run_validation(pyproject_path: Optional[str] = None) -> List[ValidationIssue]:
    issues = validate_registry(pyproject_path)
    issues.extend(validate_factory_dep_keys(build_factory_dep_keys()))
    return issues


# ── CLI entry point ────────────────────────────────────────────────────

def _cli_check() -> None:
    issues = run_validation()
    for issue in issues:
        print(issue)
    if issues:
        print(f"\nFound {len(issues)} issue(s). Fix before merging.")
        sys.exit(1)
    else:
        print("All dependency registry checks passed.")


if __name__ == "__main__":
    _cli_check()


# ── LLMs ──────────────────────────────────────────────────────────────
register("ollama",             "llm", ["ollama"],                       "llms",   ["ollama"],              factory_name="ollama")
register("groq",               "llm", ["groq"],                         "llms",   ["groq"],                factory_name="groq")
register("together",           "llm", ["together"],                     "llms",   ["together"],            factory_name="together")
register("litellm",            "llm", ["litellm"],                      "llms",   ["litellm"],             factory_name="litellm")
register("anthropic",          "llm", ["anthropic"],                    "llms",   ["anthropic"],           factory_name="anthropic")
register("gemini",             "llm", ["google.genai"],                 "llms",   ["google-genai"],        factory_name="gemini")
register("aws_bedrock",        "llm", ["boto3"],                        "extras", ["boto3"],               factory_name="aws_bedrock")
register("langchain",          "llm", ["langchain.chat_models.base", "langchain_core.messages"], "extras", ["langchain", "langchain-core"], factory_name="langchain")

# ── Embeddings ────────────────────────────────────────────────────────
register("ollama_emb",         "embedding", ["ollama"],                 "llms",   ["ollama"],              factory_name="ollama")
register("huggingface",        "embedding", ["sentence_transformers"],  "extras", ["sentence-transformers"], factory_name="huggingface")
register("azure_openai_emb",   "embedding", ["azure.identity", "openai"], "extras", ["azure-identity"],   factory_name="azure_openai")
register("gemini_emb",         "embedding", ["google.genai"],           "llms",   ["google-genai"],        factory_name="gemini")
register("vertexai_emb",       "embedding", ["vertexai"],               "llms",   ["vertexai"],            factory_name="vertexai")
register("together_emb",       "embedding", ["together"],               "llms",   ["together"],            factory_name="together")
register("aws_bedrock_emb",    "embedding", ["boto3"],                  "extras", ["boto3"],               factory_name="aws_bedrock")
register("fastembed",          "embedding", ["fastembed"],              "extras", ["fastembed"],            factory_name="fastembed")
register("langchain_emb",      "embedding", ["langchain.embeddings.base"], "extras", ["langchain"],        factory_name="langchain")

# ── Vector stores ─────────────────────────────────────────────────────
register("chroma",             "vector_store", ["chromadb"],            "vector-stores", ["chromadb"],     factory_name="chroma")
register("pgvector",           "vector_store", ["psycopg"],             "vector-stores", ["psycopg", "psycopg-pool"], factory_name="pgvector")
register("milvus",             "vector_store", ["pymilvus"],            "vector-stores", ["pymilvus"],     factory_name="milvus")
register("upstash_vector",     "vector_store", ["upstash_vector"],      "vector-stores", ["upstash-vector"], factory_name="upstash_vector")
register("pinecone",           "vector_store", ["pinecone"],            "vector-stores", ["pinecone", "pinecone-text"], factory_name="pinecone")
register("weaviate",           "vector_store", ["weaviate"],            "vector-stores", ["weaviate-client"], factory_name="weaviate")
register("qdrant_extra",       "vector_store", ["fastembed"],           "extras",  ["fastembed"])
register("supabase",           "vector_store", ["vecs"],                "vector-stores", ["vecs"],         factory_name="supabase")
register("azure_ai_search",    "vector_store", ["azure.search.documents"], "vector-stores", ["azure-search-documents", "azure-identity"], factory_name="azure_ai_search")
register("azure_mysql",        "vector_store", ["pymysql", "dbutils", "azure.identity"], "vector-stores", ["pymysql", "dbutils", "azure-identity"], factory_name="azure_mysql")
register("mongodb",            "vector_store", ["pymongo"],             "vector-stores", ["pymongo"],      factory_name="mongodb")
register("redis_vs",           "vector_store", ["redis", "redisvl"],    "vector-stores", ["redis", "redisvl"], factory_name="redis")
register("valkey_vs",          "vector_store", ["valkey"],              "vector-stores", ["valkey"],       factory_name="valkey")
register("elasticsearch_vs",   "vector_store", ["elasticsearch"],      "vector-stores", ["elasticsearch"], factory_name="elasticsearch")
register("opensearch",         "vector_store", ["opensearchpy"],        "extras",  ["opensearch-py"],      factory_name="opensearch")
register("faiss",              "vector_store", ["faiss"],               "vector-stores", ["faiss-cpu"],    factory_name="faiss")
register("cassandra",          "vector_store", ["cassandra.cluster"],   "vector-stores", ["cassandra-driver"], factory_name="cassandra")
register("databricks",         "vector_store", ["databricks.sdk"],      "vector-stores", ["databricks-sdk"], factory_name="databricks")
register("baidu",              "vector_store", ["pymochow"],            "vector-stores", ["pymochow"],     factory_name="baidu")
register("neptune",            "vector_store", ["langchain_aws"],       "vector-stores", ["langchain-aws"], factory_name="neptune")
register("turbopuffer",        "vector_store", ["turbopuffer"],         "vector-stores", ["turbopuffer"],  factory_name="turbopuffer")
register("s3_vectors",         "vector_store", ["boto3"],               "extras",  ["boto3"],              factory_name="s3_vectors")
register("langchain_vs",       "vector_store", ["langchain_community.vectorstores"], "extras", ["langchain-community"], factory_name="langchain")
register("vertex_ai_vector_search", "vector_store", ["vertexai"],      "llms",    ["vertexai"],           factory_name="vertex_ai_vector_search")

# ── Rerankers ─────────────────────────────────────────────────────────
register("cohere_reranker",       "reranker", ["cohere"],               "extras",  ["cohere"],           factory_name="cohere")
register("sentence_transformer",  "reranker", ["sentence_transformers"], "extras",  ["sentence-transformers"], factory_name="sentence_transformer")
register("huggingface_reranker",  "reranker", ["transformers", "torch"], None,      ["transformers", "torch"], factory_name="huggingface")
register("zero_entropy",          "reranker", ["zeroentropy"],          None,      ["zeroentropy"],        factory_name="zero_entropy")

# ── Extras / cross-cutting ────────────────────────────────────────────
register("spacy",              "nlp",  ["spacy"],                       "nlp",    ["spacy"])
