import os
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from mem0.configs.rerankers.config import RerankerConfig
from mem0.embeddings.configs import EmbedderConfig
from mem0.llms.configs import LlmConfig
from mem0.vector_stores.configs import VectorStoreConfig


class LifecyclePolicyConfig(BaseModel):
    """Configurable lifecycle / retention policy.

    default_ttl_days: default TTL in days applied when no per-request override
                      or higher-scope policy is present. None = permanent.
    enabled: whether this policy scope is active.
    """

    default_ttl_days: Optional[int] = Field(
        None,
        description="Default retention period in days. None means permanent.",
    )
    enabled: bool = Field(True, description="Whether the policy is active.")


class LifecyclePoliciesConfig(BaseModel):
    """Hierarchy of lifecycle policies.

    Scope precedence (highest → lowest):
      request > category > user > agent > workspace > default

    - `default`, `workspace`: singleton policy dicts (single policy per scope).
    - `users`, `agents`, `categories`: keyed by entity/category ID to the
      per-entity policy. Omitted keys fall back to the next lower scope.
    """

    default: LifecyclePolicyConfig = Field(
        default_factory=LifecyclePolicyConfig,
        description="Fallback policy when no higher-scope policy applies.",
    )
    workspace: Optional[LifecyclePolicyConfig] = Field(
        None,
        description="Workspace-wide default policy (if applicable).",
    )
    users: Dict[str, LifecyclePolicyConfig] = Field(
        default_factory=dict,
        description="Per-user policies keyed by user_id.",
    )
    agents: Dict[str, LifecyclePolicyConfig] = Field(
        default_factory=dict,
        description="Per-agent policies keyed by agent_id.",
    )
    categories: Dict[str, LifecyclePolicyConfig] = Field(
        default_factory=dict,
        description="Per-category policies keyed by category name.",
    )

# Set up the directory path
home_dir = os.path.expanduser("~")
mem0_dir = os.environ.get("MEM0_DIR") or os.path.join(home_dir, ".mem0")


class MemoryItem(BaseModel):
    id: str = Field(..., description="The unique identifier for the text data")
    memory: str = Field(
        ..., description="The memory deduced from the text data"
    )  # TODO After prompt changes from platform, update this
    hash: Optional[str] = Field(None, description="The hash of the memory")
    # The metadata value can be anything and not just string. Fix it
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata for the text data")
    score: Optional[float] = Field(None, description="The score associated with the text data")
    created_at: Optional[str] = Field(None, description="The timestamp when the memory was created")
    updated_at: Optional[str] = Field(None, description="The timestamp when the memory was updated")
    expires_at: Optional[str] = Field(
        None,
        description="ISO 8601 UTC timestamp when the memory expires, or None for permanent.",
    )
    ttl_state: Optional[str] = Field(
        None,
        description='TTL lifecycle state: "active" | "expiring_soon" | "expired" | "permanent".',
    )
    ttl_source: Optional[str] = Field(
        None,
        description='Which policy scope produced expires_at: "default" | "category" | "user" | "agent" | "workspace" | "request".',
    )


class MemoryConfig(BaseModel):
    vector_store: VectorStoreConfig = Field(
        description="Configuration for the vector store",
        default_factory=VectorStoreConfig,
    )
    llm: LlmConfig = Field(
        description="Configuration for the language model",
        default_factory=LlmConfig,
    )
    embedder: EmbedderConfig = Field(
        description="Configuration for the embedding model",
        default_factory=EmbedderConfig,
    )
    history_db_path: str = Field(
        description="Path to the history database",
        default=os.path.join(mem0_dir, "history.db"),
    )
    reranker: Optional[RerankerConfig] = Field(
        description="Configuration for the reranker",
        default=None,
    )
    version: str = Field(
        description="The version of the API",
        default="v1.1",
    )
    custom_instructions: Optional[str] = Field(
        description="Custom instructions for fact extraction",
        default=None,
    )
    lifecycle_policies: LifecyclePoliciesConfig = Field(
        description="Memory lifecycle / retention policies",
        default_factory=LifecyclePoliciesConfig,
    )


class AzureConfig(BaseModel):
    """
    Configuration settings for Azure.

    Args:
        api_key (str): The API key used for authenticating with the Azure service.
        azure_deployment (str): The name of the Azure deployment.
        azure_endpoint (str): The endpoint URL for the Azure service.
        api_version (str): The version of the Azure API being used.
        default_headers (Dict[str, str]): Headers to include in requests to the Azure API.
    """

    api_key: str = Field(
        description="The API key used for authenticating with the Azure service.",
        default=None,
    )
    azure_deployment: str = Field(description="The name of the Azure deployment.", default=None)
    azure_endpoint: str = Field(description="The endpoint URL for the Azure service.", default=None)
    api_version: str = Field(description="The version of the Azure API being used.", default=None)
    default_headers: Optional[Dict[str, str]] = Field(
        description="Headers to include in requests to the Azure API.", default=None
    )
