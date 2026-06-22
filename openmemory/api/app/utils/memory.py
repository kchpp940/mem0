"""
Memory client utilities for OpenMemory.

This module provides functionality to initialize and manage the Mem0 memory client
with automatic configuration management and Docker environment support.

Docker Ollama Configuration:
When running inside a Docker container and using Ollama as the LLM or embedder provider,
the system automatically detects the Docker environment and adjusts localhost URLs
to properly reach the host machine where Ollama is running.

Supported Docker host resolution (in order of preference):
1. OLLAMA_HOST environment variable (if set)
2. host.docker.internal (Docker Desktop for Mac/Windows)
3. Docker bridge gateway IP (typically 172.17.0.1 on Linux)
4. Fallback to 172.17.0.1

Example configuration that will be automatically adjusted:
{
    "llm": {
        "provider": "ollama",
        "config": {
            "model": "llama3.1:latest",
            "ollama_base_url": "http://localhost:11434"  # Auto-adjusted in Docker
        }
    }
}
"""

import hashlib
import json
import logging
import os
import socket
import sys

from app.database import SessionLocal
from app.models import Config as ConfigModel

from mem0 import Memory
from mem0.configs.env_loader import (
    ConfigError,
    ConfigValidationError,
    fatal_config_error,
    get_env,
    get_env_int,
    load_env,
)

load_env()

_memory_client = None
_config_hash = None


def _get_config_hash(config_dict):
    """Generate a hash of the config to detect changes."""
    config_str = json.dumps(config_dict, sort_keys=True)
    return hashlib.md5(config_str.encode()).hexdigest()


def _get_docker_host_url():
    """
    Determine the appropriate host URL to reach host machine from inside Docker container.
    Returns the best available option for reaching the host from inside a container.
    """
    # Check for custom environment variable first
    custom_host = os.environ.get('OLLAMA_HOST')
    if custom_host:
        print(f"Using custom Ollama host from OLLAMA_HOST: {custom_host}")
        return custom_host.replace('http://', '').replace('https://', '').split(':')[0]
    
    # Check if we're running inside Docker
    if not os.path.exists('/.dockerenv'):
        # Not in Docker, return localhost as-is
        return "localhost"
    
    print("Detected Docker environment, adjusting host URL for Ollama...")
    
    # Try different host resolution strategies
    host_candidates = []
    
    # 1. host.docker.internal (works on Docker Desktop for Mac/Windows)
    try:
        socket.gethostbyname('host.docker.internal')
        host_candidates.append('host.docker.internal')
        print("Found host.docker.internal")
    except socket.gaierror:
        pass
    
    # 2. Docker bridge gateway (typically 172.17.0.1 on Linux)
    try:
        with open('/proc/net/route', 'r') as f:
            for line in f:
                fields = line.strip().split()
                if fields[1] == '00000000':  # Default route
                    gateway_hex = fields[2]
                    gateway_ip = socket.inet_ntoa(bytes.fromhex(gateway_hex)[::-1])
                    host_candidates.append(gateway_ip)
                    print(f"Found Docker gateway: {gateway_ip}")
                    break
    except (FileNotFoundError, IndexError, ValueError):
        pass
    
    # 3. Fallback to common Docker bridge IP
    if not host_candidates:
        host_candidates.append('172.17.0.1')
        print("Using fallback Docker bridge IP: 172.17.0.1")
    
    # Return the first available candidate
    return host_candidates[0]


def _fix_ollama_urls(config_section):
    """
    Fix Ollama URLs for Docker environment.
    Replaces localhost URLs with appropriate Docker host URLs.
    Sets default ollama_base_url if not provided.
    """
    if not config_section or "config" not in config_section:
        return config_section
    
    ollama_config = config_section["config"]
    
    # Set default ollama_base_url if not provided
    if "ollama_base_url" not in ollama_config:
        ollama_config["ollama_base_url"] = "http://host.docker.internal:11434"
    else:
        # Check for ollama_base_url and fix if it's localhost
        url = ollama_config["ollama_base_url"]
        if "localhost" in url or "127.0.0.1" in url:
            docker_host = _get_docker_host_url()
            if docker_host != "localhost":
                new_url = url.replace("localhost", docker_host).replace("127.0.0.1", docker_host)
                ollama_config["ollama_base_url"] = new_url
                print(f"Adjusted Ollama URL from {url} to {new_url}")
    
    return config_section


def reset_memory_client():
    """Reset the global memory client to force reinitialization with new config."""
    global _memory_client, _config_hash
    _memory_client = None
    _config_hash = None


# --- LLM provider config factories ---

def _build_ollama_llm_config(model, api_key, base_url, ollama_base_url):
    config = {"model": model or "llama3.1:latest"}
    # OLLAMA_BASE_URL takes precedence, then LLM_BASE_URL, then default
    config["ollama_base_url"] = ollama_base_url or base_url or "http://localhost:11434"
    return config


def _build_openai_llm_config(model, api_key, base_url, ollama_base_url):
    config = {
        "model": model or "gpt-4o-mini",
        "api_key": api_key or "env:OPENAI_API_KEY",
    }
    if base_url:
        config["openai_base_url"] = base_url
    return config


_LLM_CONFIG_FACTORIES = {
    "ollama": _build_ollama_llm_config,
    "openai": _build_openai_llm_config,
}


def _create_llm_config(provider, model, api_key, base_url, ollama_base_url):
    """Build LLM config using registered provider factory or generic fallback."""
    base_config = {
        "temperature": 0.1,
        "max_tokens": 2000,
    }

    factory = _LLM_CONFIG_FACTORIES.get(provider)
    if factory:
        base_config.update(factory(model, api_key, base_url, ollama_base_url))
    else:
        # Generic provider (anthropic, groq, together, deepseek, etc.)
        if not model:
            raise ValueError(
                f"LLM_MODEL environment variable is required when using LLM_PROVIDER='{provider}'. "
                f"Set LLM_MODEL to a valid model name for the '{provider}' provider."
            )
        base_config["model"] = model
        if api_key:
            base_config["api_key"] = api_key

    return base_config


# --- Embedder provider config factories ---

def _build_ollama_embedder_config(model, api_key, base_url, ollama_base_url, llm_base_url):
    config = {"model": model or "nomic-embed-text"}
    config["ollama_base_url"] = base_url or ollama_base_url or llm_base_url or "http://localhost:11434"
    return config


def _build_openai_embedder_config(model, api_key, base_url, ollama_base_url, llm_base_url):
    config = {
        "model": model or "text-embedding-3-small",
        "api_key": api_key or "env:OPENAI_API_KEY",
    }
    if base_url:
        config["openai_base_url"] = base_url
    return config


_EMBEDDER_CONFIG_FACTORIES = {
    "ollama": _build_ollama_embedder_config,
    "openai": _build_openai_embedder_config,
}


def _create_embedder_config(provider, model, api_key, base_url, ollama_base_url, llm_base_url):
    """Build embedder config using registered provider factory or generic fallback."""
    factory = _EMBEDDER_CONFIG_FACTORIES.get(provider)
    if factory:
        config = factory(model, api_key, base_url, ollama_base_url, llm_base_url)
    else:
        if not model:
            raise ValueError(
                f"EMBEDDER_MODEL environment variable is required when using EMBEDDER_PROVIDER='{provider}'. "
                f"Set EMBEDDER_MODEL to a valid model name for the '{provider}' provider."
            )
        config = {"model": model}
        if api_key:
            config["api_key"] = api_key

    return config


def _resolve_env(new_name: str, old_name: str, default: str = "") -> str:
    """Resolve an env var, preferring the new unified name and falling back to the legacy name."""
    val = get_env(new_name, "")
    if val:
        return val
    val = get_env(old_name, "")
    if val:
        return val
    return default


def _resolve_env_int(new_name: str, old_name: str, default: int) -> int:
    val = get_env_int(new_name, None)
    if val is not None:
        return val
    raw = os.environ.get(old_name)
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return default


def validate_startup_config() -> None:
    """Validate critical configuration at startup time and exit with a helpful message on failure."""
    errors: list[ConfigError] = []

    llm_provider = _resolve_env("MEM0_LLM_PROVIDER", "LLM_PROVIDER", "openai").lower()
    if llm_provider == "openai" and not _resolve_env("OPENAI_API_KEY", "OPENAI_API_KEY", ""):
        errors.append(
            ConfigError(
                key="OPENAI_API_KEY",
                message="LLM provider is 'openai' but OPENAI_API_KEY is not set.",
                suggestion="Set OPENAI_API_KEY=<your-key> in your .env file, or choose a different MEM0_LLM_PROVIDER (e.g. ollama, anthropic, gemini).",
            )
        )

    vector_store_provider = _resolve_env("VECTOR_STORE_PROVIDER", "VECTOR_STORE", "qdrant").lower()
    has_vector_store = False
    if vector_store_provider == "qdrant":
        has_vector_store = bool(_resolve_env("QDRANT_HOST", "QDRANT_HOST", ""))
    elif vector_store_provider == "pgvector":
        has_vector_store = bool(_resolve_env("POSTGRES_HOST", "PG_HOST", "")) or bool(
            _resolve_env("POSTGRES_PASSWORD", "PG_PASSWORD", "")
        )
    elif vector_store_provider == "chroma":
        has_vector_store = bool(_resolve_env("CHROMA_HOST", "CHROMA_HOST", ""))
    elif vector_store_provider == "redis":
        has_vector_store = bool(_resolve_env("REDIS_URL", "REDIS_URL", ""))
    elif vector_store_provider == "weaviate":
        has_vector_store = bool(_resolve_env("WEAVIATE_HOST", "WEAVIATE_HOST", ""))
    elif vector_store_provider == "milvus":
        has_vector_store = bool(_resolve_env("MILVUS_HOST", "MILVUS_HOST", ""))
    elif vector_store_provider == "elasticsearch":
        has_vector_store = bool(_resolve_env("ELASTICSEARCH_HOST", "ELASTICSEARCH_HOST", ""))
    elif vector_store_provider == "faiss":
        has_vector_store = True

    if not has_vector_store and vector_store_provider != "faiss":
        errors.append(
            ConfigError(
                key=f"VECTOR_STORE_PROVIDER={vector_store_provider}",
                message=(
                    f"VECTOR_STORE_PROVIDER is '{vector_store_provider}' but no connection "
                    f"environment variables were found for it."
                ),
                suggestion=(
                    f"For {vector_store_provider}, set the corresponding env vars "
                    f"(e.g. QDRANT_HOST/QDRANT_PORT, POSTGRES_*, CHROMA_HOST/CHROMA_PORT, "
                    f"REDIS_URL, etc.). See the root .env.example for the full list."
                ),
            )
        )

    if errors:
        try:
            raise ConfigValidationError(errors)
        except ConfigValidationError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)


def get_default_memory_config():
    """Get default memory client configuration with sensible defaults.

    Supports both the unified MEM0_* / VECTOR_STORE_PROVIDER naming and the
    legacy per-vendor env var names for backward compatibility.
    """
    validate_startup_config()

    vector_store_provider = _resolve_env("VECTOR_STORE_PROVIDER", "VECTOR_STORE", "qdrant").lower()
    collection_name = _resolve_env("POSTGRES_COLLECTION_NAME", "POSTGRES_COLLECTION_NAME", "openmemory")

    vector_store_config = {"collection_name": collection_name}

    if vector_store_provider == "chroma":
        vector_store_config.update(
            {
                "host": _resolve_env("CHROMA_HOST", "CHROMA_HOST", "mem0_store"),
                "port": _resolve_env_int("CHROMA_PORT", "CHROMA_PORT", 8000),
            }
        )
    elif vector_store_provider == "qdrant":
        vector_store_config.update(
            {
                "host": _resolve_env("QDRANT_HOST", "QDRANT_HOST", "mem0_store"),
                "port": _resolve_env_int("QDRANT_PORT", "QDRANT_PORT", 6333),
            }
        )
    elif vector_store_provider == "weaviate":
        cluster_url = _resolve_env("WEAVIATE_CLUSTER_URL", "WEAVIATE_CLUSTER_URL", "")
        if not cluster_url:
            host = _resolve_env("WEAVIATE_HOST", "WEAVIATE_HOST", "mem0_store")
            port = _resolve_env_int("WEAVIATE_PORT", "WEAVIATE_PORT", 8080)
            cluster_url = f"http://{host}:{port}"
        vector_store_config = {"collection_name": collection_name, "cluster_url": cluster_url}
    elif vector_store_provider == "redis":
        vector_store_config = {
            "collection_name": collection_name,
            "redis_url": _resolve_env("REDIS_URL", "REDIS_URL", "redis://localhost:6379"),
        }
    elif vector_store_provider == "pgvector":
        vector_store_config.update(
            {
                "host": _resolve_env("POSTGRES_HOST", "PG_HOST", "mem0_store"),
                "port": _resolve_env_int("POSTGRES_PORT", "PG_PORT", 5432),
                "dbname": _resolve_env("POSTGRES_DB", "PG_DB", "mem0"),
                "user": _resolve_env("POSTGRES_USER", "PG_USER", "mem0"),
                "password": _resolve_env("POSTGRES_PASSWORD", "PG_PASSWORD", "mem0"),
            }
        )
    elif vector_store_provider == "milvus":
        host = _resolve_env("MILVUS_HOST", "MILVUS_HOST", "mem0_store")
        port = _resolve_env_int("MILVUS_PORT", "MILVUS_PORT", 19530)
        vector_store_config = {
            "collection_name": collection_name,
            "url": f"http://{host}:{port}",
            "token": _resolve_env("MILVUS_TOKEN", "MILVUS_TOKEN", ""),
            "db_name": _resolve_env("MILVUS_DB_NAME", "MILVUS_DB_NAME", ""),
            "embedding_model_dims": 1536,
            "metric_type": "COSINE",
        }
    elif vector_store_provider == "elasticsearch":
        host = _resolve_env("ELASTICSEARCH_HOST", "ELASTICSEARCH_HOST", "mem0_store")
        if not host.startswith("http"):
            host = f"http://{host}"
        vector_store_config.update(
            {
                "host": host,
                "port": _resolve_env_int("ELASTICSEARCH_PORT", "ELASTICSEARCH_PORT", 9200),
                "user": _resolve_env("ELASTICSEARCH_USER", "ELASTICSEARCH_USER", "elastic"),
                "password": _resolve_env("ELASTICSEARCH_PASSWORD", "ELASTICSEARCH_PASSWORD", "changeme"),
                "verify_certs": False,
                "use_ssl": False,
                "embedding_model_dims": 1536,
            }
        )
    elif vector_store_provider == "opensearch":
        vector_store_config.update(
            {
                "host": _resolve_env("OPENSEARCH_HOST", "OPENSEARCH_HOST", "mem0_store"),
                "port": _resolve_env_int("OPENSEARCH_PORT", "OPENSEARCH_PORT", 9200),
            }
        )
    elif vector_store_provider == "faiss":
        vector_store_config = {
            "collection_name": collection_name,
            "path": _resolve_env("FAISS_PATH", "FAISS_PATH", "/tmp/faiss"),
            "embedding_model_dims": 1536,
            "distance_strategy": "cosine",
        }
    else:
        logging.warning(
            "Unknown VECTOR_STORE_PROVIDER='%s', falling back to qdrant defaults.",
            vector_store_provider,
        )
        vector_store_provider = "qdrant"
        vector_store_config.update({"host": "mem0_store", "port": 6333})

    logging.info(
        "Auto-detected vector store: %s (host=%s)",
        vector_store_provider,
        vector_store_config.get("host") or vector_store_config.get("cluster_url") or vector_store_config.get("path"),
    )

    llm_provider = _resolve_env("MEM0_LLM_PROVIDER", "LLM_PROVIDER", "openai").lower()
    llm_model = _resolve_env("MEM0_DEFAULT_LLM_MODEL", "LLM_MODEL", "")
    llm_api_key = _resolve_env("LLM_API_KEY", "LLM_API_KEY", "")
    llm_base_url = _resolve_env("LLM_BASE_URL", "LLM_BASE_URL", "")
    ollama_base_url = _resolve_env("OLLAMA_BASE_URL", "OLLAMA_BASE_URL", "")

    llm_config = _create_llm_config(
        provider=llm_provider,
        model=llm_model,
        api_key=llm_api_key,
        base_url=llm_base_url,
        ollama_base_url=ollama_base_url,
    )
    logging.info("Auto-detected LLM provider: %s (model=%s)", llm_provider, llm_config.get("model"))

    default_embedder = llm_provider if llm_provider == "ollama" else "openai"
    embedder_provider = _resolve_env("MEM0_EMBEDDER_PROVIDER", "EMBEDDER_PROVIDER", default_embedder).lower()
    embedder_model = _resolve_env("MEM0_DEFAULT_EMBEDDER_MODEL", "EMBEDDER_MODEL", "")
    embedder_api_key = _resolve_env("EMBEDDER_API_KEY", "EMBEDDER_API_KEY", "")
    embedder_base_url = _resolve_env("EMBEDDER_BASE_URL", "EMBEDDER_BASE_URL", "")

    embedder_config = _create_embedder_config(
        provider=embedder_provider,
        model=embedder_model,
        api_key=embedder_api_key,
        base_url=embedder_base_url,
        ollama_base_url=ollama_base_url,
        llm_base_url=llm_base_url,
    )
    logging.info(
        "Auto-detected embedder provider: %s (model=%s)",
        embedder_provider,
        embedder_config.get("model"),
    )

    return {
        "vector_store": {"provider": vector_store_provider, "config": vector_store_config},
        "llm": {"provider": llm_provider, "config": llm_config},
        "embedder": {"provider": embedder_provider, "config": embedder_config},
        "version": "v1.1",
    }


def _parse_environment_variables(config_dict):
    """
    Parse environment variables in config values.
    Converts 'env:VARIABLE_NAME' to actual environment variable values.
    """
    if isinstance(config_dict, dict):
        parsed_config = {}
        for key, value in config_dict.items():
            if isinstance(value, str) and value.startswith("env:"):
                env_var = value.split(":", 1)[1]
                env_value = os.environ.get(env_var)
                if env_value:
                    parsed_config[key] = env_value
                    print(f"Loaded {env_var} from environment for {key}")
                else:
                    print(f"Warning: Environment variable {env_var} not found, keeping original value")
                    parsed_config[key] = value
            elif isinstance(value, dict):
                parsed_config[key] = _parse_environment_variables(value)
            else:
                parsed_config[key] = value
        return parsed_config
    return config_dict


def get_memory_client(custom_instructions: str = None):
    """
    Get or initialize the Mem0 client.

    Args:
        custom_instructions: Optional instructions for the memory project.

    Returns:
        Initialized Mem0 client instance or None if initialization fails.

    Raises:
        Exception: If required API keys are not set or critical configuration is missing.
    """
    global _memory_client, _config_hash

    try:
        # Start with default configuration
        config = get_default_memory_config()
        
        # Variable to track custom instructions
        db_custom_instructions = None
        
        # Load configuration from database
        try:
            db = SessionLocal()
            db_config = db.query(ConfigModel).filter(ConfigModel.key == "main").first()
            
            if db_config:
                json_config = db_config.value
                
                # Extract custom instructions from openmemory settings
                if "openmemory" in json_config and "custom_instructions" in json_config["openmemory"]:
                    db_custom_instructions = json_config["openmemory"]["custom_instructions"]
                
                # Override defaults with configurations from the database
                if "mem0" in json_config:
                    mem0_config = json_config["mem0"]
                    
                    # Update LLM configuration if available
                    if "llm" in mem0_config and mem0_config["llm"] is not None:
                        config["llm"] = mem0_config["llm"]

                    # Update Embedder configuration if available
                    if "embedder" in mem0_config and mem0_config["embedder"] is not None:
                        config["embedder"] = mem0_config["embedder"]

                    if "vector_store" in mem0_config and mem0_config["vector_store"] is not None:
                        config["vector_store"] = mem0_config["vector_store"]
            else:
                print("No configuration found in database, using defaults")
                    
            db.close()
                            
        except Exception as e:
            print(f"Warning: Error loading configuration from database: {e}")
            print("Using default configuration")
            # Continue with default configuration if database config can't be loaded

        # Use custom_instructions parameter first, then fall back to database value
        instructions_to_use = custom_instructions or db_custom_instructions
        if instructions_to_use:
            config["custom_fact_extraction_prompt"] = instructions_to_use

        # Fix Ollama URLs for Docker environment (applies to both env-var defaults and DB overrides)
        if config.get("llm", {}).get("provider") == "ollama":
            config["llm"] = _fix_ollama_urls(config["llm"])
        if config.get("embedder", {}).get("provider") == "ollama":
            config["embedder"] = _fix_ollama_urls(config["embedder"])

        # ALWAYS parse environment variables in the final config
        # This ensures that even default config values like "env:OPENAI_API_KEY" get parsed
        print("Parsing environment variables in final config...")
        config = _parse_environment_variables(config)

        # Check if config has changed by comparing hashes
        current_config_hash = _get_config_hash(config)
        
        # Only reinitialize if config changed or client doesn't exist
        if _memory_client is None or _config_hash != current_config_hash:
            print(f"Initializing memory client with config hash: {current_config_hash}")
            try:
                _memory_client = Memory.from_config(config_dict=config)
                _config_hash = current_config_hash
                print("Memory client initialized successfully")
            except Exception as init_error:
                print(f"Warning: Failed to initialize memory client: {init_error}")
                print("Server will continue running with limited memory functionality")
                _memory_client = None
                _config_hash = None
                return None
        
        return _memory_client
        
    except Exception as e:
        print(f"Warning: Exception occurred while initializing memory client: {e}")
        print("Server will continue running with limited memory functionality")
        return None


def get_default_user_id():
    return "default_user"
