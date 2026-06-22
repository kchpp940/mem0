import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DepInfo:
    provider: str
    category: str
    import_packages: List[str]
    extras: Optional[str]
    pip_packages: List[str]
    factory_name: Optional[str]
    adapter_module: Optional[str]
    adapter_class: Optional[str]
    adapter_class_path: Optional[str]


_REGISTRY: Dict[str, DepInfo] = {}


def register(
    provider: str,
    category: str,
    import_packages: List[str],
    extras: Optional[str] = None,
    pip_packages: Optional[List[str]] = None,
    factory_name: Optional[str] = None,
    adapter_module: Optional[str] = None,
    adapter_class: Optional[str] = None,
) -> None:
    adapter_class_path = None
    if adapter_module and adapter_class:
        adapter_class_path = f"{adapter_module}.{adapter_class}"
    _REGISTRY[provider] = DepInfo(
        provider=provider,
        category=category,
        import_packages=import_packages,
        extras=extras,
        pip_packages=pip_packages or import_packages,
        factory_name=factory_name,
        adapter_module=adapter_module,
        adapter_class=adapter_class,
        adapter_class_path=adapter_class_path,
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


def optional_import(provider: str, symbol: Optional[str] = None) -> Any:
    """统一可选导入 helper。

    使用方式:
        optional_import("cohere_reranker")                              # 仅检查依赖，不返回值
        cohere = optional_import("cohere_reranker", "cohere")           # import cohere
        Client = optional_import("cohere_reranker", "cohere.Client")    # from cohere import Client
        Tag = optional_import("redis_vs", "redisvl.query.filter.Tag")   # from redisvl.query.filter import Tag

    Args:
        provider: registry 中的 dep_key
        symbol: 可选的符号路径（"module" 或 "module.ClassName" 或 "module.submodule.ClassName"）

    Returns:
        None（仅检查时）或导入的模块/符号

    Raises:
        ImportError: provider 不存在或任何 import_packages 无法导入时
    """
    info = _REGISTRY.get(provider)
    if info is None:
        raise ImportError(f"Unknown provider: {provider}")
    import importlib
    last_err = None
    for pkg in info.import_packages:
        try:
            importlib.import_module(pkg)
        except ImportError as e:
            last_err = e
    if last_err is not None:
        raise make_import_error(provider) from last_err
    if symbol is None:
        return None
    parts = symbol.split(".")
    mod = importlib.import_module(parts[0])
    for part in parts[1:]:
        mod = getattr(mod, part)
    return mod


def require_adapter_class(dep_key: str) -> type:
    """从 registry 声明的 adapter_module 中解析 adapter_class 并返回。

    用于 validate_adapters() 中做静态解析校验，也可以在运行时动态加载适配器类。

    Args:
        dep_key: registry 中的 dep_key

    Returns:
        解析到的 adapter class 对象

    Raises:
        ValueError: registry 中没有 adapter 契约
        ImportError: adapter_module 无法导入
        AttributeError: adapter_module 中找不到 adapter_class
    """
    info = _REGISTRY.get(dep_key)
    if info is None:
        raise ValueError(f"Unknown provider: {dep_key}")
    if info.adapter_module is None or info.adapter_class is None:
        raise ValueError(f"Provider {dep_key} has no adapter contract in registry")
    import importlib
    mod = importlib.import_module(info.adapter_module)
    cls = getattr(mod, info.adapter_class)
    return cls


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


# ── Adapter contract scanning ────────────────────────────────────

def _module_to_path(module: str) -> Path:
    parts = module.split(".")
    return Path(__file__).resolve().parents[1].joinpath(*parts[:-1], f"{parts[-1]}.py")


def _scan_adapter_keys(repo_root: Path) -> Dict[str, List[str]]:
    mem0_root = repo_root / "mem0"
    pattern = re.compile(r'make_import_error\(\s*["\']([^"\']+)["\']')
    result: Dict[str, List[str]] = {}
    for py_file in sorted(mem0_root.rglob("*.py")):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        keys = pattern.findall(content)
        if not keys:
            continue
        rel = str(py_file.relative_to(repo_root)).replace("/", ".")[:-3]
        result[rel] = keys
    return result


def _collect_factory_paths() -> Dict[str, Dict[str, str]]:
    from mem0.utils.factory import (
        EmbedderFactory,
        LlmFactory,
        RerankerFactory,
        VectorStoreFactory,
    )
    result: Dict[str, Dict[str, str]] = {}
    factories = {
        "llm": LlmFactory.provider_to_class,
        "embedding": EmbedderFactory.provider_to_class,
        "vector_store": VectorStoreFactory.provider_to_class,
        "reranker": RerankerFactory.provider_to_class,
    }
    for cat, mapping in factories.items():
        cat_paths: Dict[str, str] = {}
        for name, value in mapping.items():
            if isinstance(value, tuple):
                cat_paths[name] = value[0]
            else:
                cat_paths[name] = value
        result[cat] = cat_paths
    return result


def _class_exists_in_source(content: str, class_name: str) -> bool:
    """用 AST 静态检查源码中是否定义了指定的 class（不需要实际 import 模块）。"""
    try:
        import ast
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return True
    return False


def validate_adapters() -> List[ValidationIssue]:
    repo_root = Path(__file__).resolve().parents[2]
    issues: List[ValidationIssue] = []
    adapter_keys = _scan_adapter_keys(repo_root)
    factory_paths = _collect_factory_paths()

    optional_import_pattern = re.compile(r'optional_import\(\s*["\']([^"\']+)["\']')
    optional_import_keys: Dict[str, List[str]] = {}
    mem0_root = repo_root / "mem0"
    for py_file in sorted(mem0_root.rglob("*.py")):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        keys = optional_import_pattern.findall(content)
        if not keys:
            continue
        rel = str(py_file.relative_to(repo_root)).replace("/", ".")[:-3]
        optional_import_keys[rel] = keys

    registry_by_path: Dict[str, DepInfo] = {}
    for dep_key, info in _REGISTRY.items():
        if info.adapter_class_path:
            registry_by_path[info.adapter_class_path] = info

    for dep_key, info in _REGISTRY.items():
        if info.adapter_class_path is None:
            continue
        module_path, class_name = info.adapter_class_path.rsplit(".", 1)
        module_rel = module_path
        py_path = repo_root / (module_rel.replace(".", "/") + ".py")
        if not py_path.exists():
            issues.append(
                ValidationIssue(
                    "error",
                    dep_key,
                    f"adapter file missing: {py_path.relative_to(repo_root)}",
                )
            )
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if not _class_exists_in_source(content, class_name):
            issues.append(
                ValidationIssue(
                    "error",
                    dep_key,
                    f"class {class_name!r} not found in {py_path.relative_to(repo_root)} (registry declares {info.adapter_class_path!r})",
                )
            )

        has_try_except_import = False
        try:
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if "except ImportError" in line:
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if "raise" in lines[j] or lines[j].strip().startswith("raise"):
                            has_try_except_import = True
                            break
                    if has_try_except_import:
                        break
        except (OSError, UnicodeDecodeError):
            pass
        if has_try_except_import:
            keys_in_file = adapter_keys.get(module_rel, [])
            if dep_key not in keys_in_file:
                issues.append(
                    ValidationIssue(
                        "warning",
                        dep_key,
                        f"adapter {py_path.relative_to(repo_root)} has try/except ImportError but does not call make_import_error({dep_key!r})",
                    )
                )
        category = info.category
        factory_paths_cat = factory_paths.get(category, {})
        if info.factory_name and info.factory_name in factory_paths_cat:
            expected = factory_paths_cat[info.factory_name]
            if expected != info.adapter_class_path:
                issues.append(
                    ValidationIssue(
                        "warning",
                        dep_key,
                        f"factory.{category}[{info.factory_name!r}] points to {expected!r} but registry declares {info.adapter_class_path!r}",
                    )
                )

    for module_rel, keys in adapter_keys.items():
        for used_key in keys:
            if used_key not in _REGISTRY:
                issues.append(
                    ValidationIssue(
                        "error",
                        used_key,
                        f"{module_rel}.py uses make_import_error({used_key!r}) which is not registered in optional_deps registry",
                    )
                )

    for module_rel, keys in optional_import_keys.items():
        for used_key in keys:
            if used_key not in _REGISTRY:
                issues.append(
                    ValidationIssue(
                        "error",
                        used_key,
                        f"{module_rel}.py uses optional_import({used_key!r}) which is not registered in optional_deps registry",
                    )
                )

    return issues


def run_validation(pyproject_path: Optional[str] = None) -> List[ValidationIssue]:
    issues = validate_registry(pyproject_path)
    issues.extend(validate_factory_dep_keys(build_factory_dep_keys()))
    issues.extend(validate_adapters())
    return issues


def _cli_check() -> None:
    issues = run_validation()
    for issue in issues:
        print(issue)
    if issues:
        print(f"\nFound {len(issues)} issue(s). Fix before merging.")
        sys.exit(1)
    else:
        print("All dependency registry checks passed.")


# ── LLMs ──────────────────────────────────────────────────────
register("ollama",        "llm", ["ollama"],                "llms",   ["ollama"],              factory_name="ollama",    adapter_module="mem0.llms.ollama",              adapter_class="OllamaLLM")
register("groq",          "llm", ["groq"],                  "llms",   ["groq"],                factory_name="groq",      adapter_module="mem0.llms.groq",                adapter_class="GroqLLM")
register("together",      "llm", ["together"],              "llms",   ["together"],            factory_name="together",  adapter_module="mem0.llms.together",            adapter_class="TogetherLLM")
register("litellm",       "llm", ["litellm"],               "llms",   ["litellm"],             factory_name="litellm",   adapter_module="mem0.llms.litellm",             adapter_class="LiteLLM")
register("anthropic",     "llm", ["anthropic"],             "llms",   ["anthropic"],           factory_name="anthropic", adapter_module="mem0.llms.anthropic",         adapter_class="AnthropicLLM")
register("gemini",        "llm", ["google.genai"],        "llms",   ["google-genai"],        factory_name="gemini",    adapter_module="mem0.llms.gemini",            adapter_class="GeminiLLM")
register("aws_bedrock",   "llm", ["boto3"],                 "extras", ["boto3"],               factory_name="aws_bedrock", adapter_module="mem0.llms.aws_bedrock",       adapter_class="AWSBedrockLLM")
register("langchain",     "llm", ["langchain.chat_models.base", "langchain_core.messages"], "extras", ["langchain", "langchain-core"], factory_name="langchain", adapter_module="mem0.llms.langchain",       adapter_class="LangchainLLM")

# ── Embeddings ────────────────────────────────────────────
register("ollama_emb",     "embedding", ["ollama"],                 "llms",   ["ollama"],              factory_name="ollama",    adapter_module="mem0.embeddings.ollama",          adapter_class="OllamaEmbedding")
register("huggingface",    "embedding", ["sentence_transformers"],  "extras", ["sentence-transformers"], factory_name="huggingface", adapter_module="mem0.embeddings.huggingface",     adapter_class="HuggingFaceEmbedding")
register("azure_openai_emb",   "embedding", ["azure.identity", "openai"], "extras", ["azure-identity"],   factory_name="azure_openai", adapter_module="mem0.embeddings.azure_openai",    adapter_class="AzureOpenAIEmbedding")
register("gemini_emb",       "embedding", ["google.genai"],           "llms",   ["google-genai"],        factory_name="gemini",    adapter_module="mem0.embeddings.gemini",          adapter_class="GoogleGenAIEmbedding")
register("vertexai_emb",     "embedding", ["vertexai"],               "llms",   ["vertexai"],            factory_name="vertexai",  adapter_module="mem0.embeddings.vertexai",        adapter_class="VertexAIEmbedding")
register("together_emb",     "embedding", ["together"],               "llms",   ["together"],            factory_name="together",  adapter_module="mem0.embeddings.together",        adapter_class="TogetherEmbedding")
register("aws_bedrock_emb",  "embedding", ["boto3"],                  "extras", ["boto3"],               factory_name="aws_bedrock", adapter_module="mem0.embeddings.aws_bedrock",     adapter_class="AWSBedrockEmbedding")
register("fastembed",          "embedding", ["fastembed"],              "extras", ["fastembed"],            factory_name="fastembed", adapter_module="mem0.embeddings.fastembed",       adapter_class="FastEmbedEmbedding")
register("langchain_emb",      "embedding", ["langchain.embeddings.base"], "extras", ["langchain"],        factory_name="langchain", adapter_module="mem0.embeddings.langchain",     adapter_class="LangchainEmbedding")

# ── Vector stores ───────────────────────────────────────
register("chroma",             "vector_store", ["chromadb"],            "vector-stores", ["chromadb"],     factory_name="chroma",             adapter_module="mem0.vector_stores.chroma",             adapter_class="ChromaDB")
register("pgvector",           "vector_store", ["psycopg"],             "vector-stores", ["psycopg", "psycopg-pool"], factory_name="pgvector",           adapter_module="mem0.vector_stores.pgvector",           adapter_class="PGVector")
register("milvus",             "vector_store", ["pymilvus"],            "vector-stores", ["pymilvus"],     factory_name="milvus",             adapter_module="mem0.vector_stores.milvus",             adapter_class="MilvusDB")
register("upstash_vector",     "vector_store", ["upstash_vector"],      "vector-stores", ["upstash-vector"], factory_name="upstash_vector",     adapter_module="mem0.vector_stores.upstash_vector",     adapter_class="UpstashVector")
register("pinecone",           "vector_store", ["pinecone"],            "vector-stores", ["pinecone", "pinecone-text"], factory_name="pinecone",           adapter_module="mem0.vector_stores.pinecone",           adapter_class="PineconeDB")
register("weaviate",           "vector_store", ["weaviate"],            "vector-stores", ["weaviate-client"], factory_name="weaviate",           adapter_module="mem0.vector_stores.weaviate",           adapter_class="Weaviate")
register("qdrant_extra",       "vector_store", ["fastembed"],           "extras",  ["fastembed"])
register("supabase",           "vector_store", ["vecs"],                "vector-stores", ["vecs"],         factory_name="supabase",           adapter_module="mem0.vector_stores.supabase",           adapter_class="Supabase")
register("azure_ai_search",    "vector_store", ["azure.search.documents"], "vector-stores", ["azure-search-documents", "azure-identity"], factory_name="azure_ai_search",    adapter_module="mem0.vector_stores.azure_ai_search",    adapter_class="AzureAISearch")
register("azure_mysql",        "vector_store", ["pymysql", "dbutils", "azure.identity"], "vector-stores", ["pymysql", "dbutils", "azure-identity"], factory_name="azure_mysql",        adapter_module="mem0.vector_stores.azure_mysql",        adapter_class="AzureMySQL")
register("mongodb",            "vector_store", ["pymongo"],             "vector-stores", ["pymongo"],      factory_name="mongodb",            adapter_module="mem0.vector_stores.mongodb",            adapter_class="MongoDB")
register("redis_vs",           "vector_store", ["redis", "redisvl"],    "vector-stores", ["redis", "redisvl"], factory_name="redis",              adapter_module="mem0.vector_stores.redis",              adapter_class="RedisDB")
register("valkey_vs",          "vector_store", ["valkey"],              "vector-stores", ["valkey"],       factory_name="valkey",             adapter_module="mem0.vector_stores.valkey",             adapter_class="ValkeyDB")
register("elasticsearch_vs",   "vector_store", ["elasticsearch"],      "vector-stores", ["elasticsearch"], factory_name="elasticsearch",      adapter_module="mem0.vector_stores.elasticsearch",      adapter_class="ElasticsearchDB")
register("opensearch",         "vector_store", ["opensearchpy"],        "extras",  ["opensearch-py"],      factory_name="opensearch",         adapter_module="mem0.vector_stores.opensearch",         adapter_class="OpenSearchDB")
register("faiss",              "vector_store", ["faiss"],               "vector-stores", ["faiss-cpu"],    factory_name="faiss",              adapter_module="mem0.vector_stores.faiss",              adapter_class="FAISS")
register("cassandra",          "vector_store", ["cassandra.cluster"],   "vector-stores", ["cassandra-driver"], factory_name="cassandra",          adapter_module="mem0.vector_stores.cassandra",          adapter_class="CassandraDB")
register("databricks",         "vector_store", ["databricks.sdk"],      "vector-stores", ["databricks-sdk"], factory_name="databricks",         adapter_module="mem0.vector_stores.databricks",         adapter_class="Databricks")
register("baidu",              "vector_store", ["pymochow"],            "vector-stores", ["pymochow"],     factory_name="baidu",              adapter_module="mem0.vector_stores.baidu",              adapter_class="BaiduDB")
register("neptune",            "vector_store", ["langchain_aws"],       "vector-stores", ["langchain-aws"], factory_name="neptune",            adapter_module="mem0.vector_stores.neptune_analytics",  adapter_class="NeptuneAnalyticsVector")
register("turbopuffer",        "vector_store", ["turbopuffer"],         "vector-stores", ["turbopuffer"],  factory_name="turbopuffer",        adapter_module="mem0.vector_stores.turbopuffer",        adapter_class="TurbopufferDB")
register("s3_vectors",         "vector_store", ["boto3"],               "extras",  ["boto3"],              factory_name="s3_vectors",         adapter_module="mem0.vector_stores.s3_vectors",         adapter_class="S3Vectors")
register("langchain_vs",       "vector_store", ["langchain_community.vectorstores"], "extras", ["langchain-community"], factory_name="langchain",       adapter_module="mem0.vector_stores.langchain",       adapter_class="Langchain")
register("vertex_ai_vector_search", "vector_store", ["vertexai"],      "llms",    ["vertexai"],           factory_name="vertex_ai_vector_search", adapter_module="mem0.vector_stores.vertex_ai_vector_search", adapter_class="GoogleMatchingEngine")

# ── Rerankers ───────────────────────────────────────
register("cohere_reranker",       "reranker", ["cohere"],               "extras",  ["cohere"],           factory_name="cohere",               adapter_module="mem0.reranker.cohere_reranker",       adapter_class="CohereReranker")
register("sentence_transformer",  "reranker", ["sentence_transformers"], "extras",  ["sentence-transformers"], factory_name="sentence_transformer",  adapter_module="mem0.reranker.sentence_transformer_reranker", adapter_class="SentenceTransformerReranker")
register("huggingface_reranker",  "reranker", ["transformers", "torch"], None,      ["transformers", "torch"], factory_name="huggingface",          adapter_module="mem0.reranker.huggingface_reranker",  adapter_class="HuggingFaceReranker")
register("zero_entropy",          "reranker", ["zeroentropy"],          None,      ["zeroentropy"],        factory_name="zero_entropy",          adapter_module="mem0.reranker.zero_entropy_reranker",          adapter_class="ZeroEntropyReranker")

# ── Extras / cross-cutting ───────────────────────────
register("spacy",              "nlp",  ["spacy"],                       "nlp",    ["spacy"])


# ── CLI entry point (must come after all register() calls) ─────
if __name__ == "__main__":
    _cli_check()
