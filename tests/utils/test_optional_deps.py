import pytest

from mem0.utils.factory import get_factory_dep_keys
from mem0.utils.optional_deps import (
    DepInfo,
    get_all_providers,
    get_dep_info,
    make_import_error,
    validate_factory_dep_keys,
    validate_registry,
)


class TestDepInfo:
    def test_dep_info_immutable(self):
        info = DepInfo(
            provider="test",
            category="llm",
            import_packages=["test_pkg"],
            extras="test-extras",
            pip_packages=["test-pkg"],
        )
        with pytest.raises(AttributeError):
            info.provider = "changed"


class TestRegistryBasics:
    def test_get_dep_info_exists(self):
        info = get_dep_info("groq")
        assert info is not None
        assert info.provider == "groq"
        assert info.category == "llm"
        assert "groq" in info.import_packages
        assert info.extras == "llms"

    def test_get_dep_info_missing(self):
        assert get_dep_info("nonexistent_provider") is None

    def test_get_all_providers_returns_copy(self):
        providers = get_all_providers()
        assert "groq" in providers
        providers["new"] = "fake"
        assert "new" not in get_all_providers()

    def test_make_import_error_known(self):
        err = make_import_error("groq")
        assert isinstance(err, ImportError)
        msg = str(err)
        assert "groq" in msg
        assert "llm" in msg
        assert "pip install groq" in msg
        assert "mem0ai[llms]" in msg

    def test_make_import_error_unknown(self):
        err = make_import_error("unknown_provider_xyz")
        assert isinstance(err, ImportError)
        assert "Unknown provider" in str(err)
        assert "unknown_provider_xyz" in str(err)

    def test_make_import_error_no_extras(self):
        err = make_import_error("huggingface_reranker")
        msg = str(err)
        assert "pip install transformers torch" in msg
        assert "mem0ai[" not in msg


class TestRegistryPyprojectValidation:
    def test_validate_registry_no_errors(self):
        issues = validate_registry()
        errors = [i for i in issues if i.severity == "error"]
        assert not errors, f"Registry validation errors: {[str(i) for i in errors]}"

    def test_validate_registry_no_warnings_strict(self):
        issues = validate_registry()
        warnings = [i for i in issues if i.severity == "warning"]
        assert not warnings, f"Registry validation warnings: {[str(i) for i in warnings]}"

    def test_all_categories_present(self):
        providers = get_all_providers()
        categories = {info.category for info in providers.values()}
        assert "llm" in categories
        assert "embedding" in categories
        assert "vector_store" in categories
        assert "reranker" in categories

    def test_every_provider_has_import_packages(self):
        for name, info in get_all_providers().items():
            assert info.import_packages, f"Provider {name} has empty import_packages"
            assert all(p for p in info.import_packages), f"Provider {name} has empty import package name"

    def test_every_provider_has_pip_packages(self):
        for name, info in get_all_providers().items():
            assert info.pip_packages, f"Provider {name} has empty pip_packages"


class TestFactoryDepKeyValidation:
    def test_all_factory_dep_keys_exist_in_registry(self):
        factory_dep_keys = get_factory_dep_keys()
        all_issues = []
        for category, mapping in factory_dep_keys.items():
            issues = validate_factory_dep_keys(mapping, category)
            all_issues.extend(issues)
        errors = [i for i in all_issues if i.severity == "error"]
        assert not errors, f"Factory dep key errors: {[str(i) for i in errors]}"

    def test_all_factory_dep_keys_category_match(self):
        factory_dep_keys = get_factory_dep_keys()
        all_issues = []
        for category, mapping in factory_dep_keys.items():
            issues = validate_factory_dep_keys(mapping, category)
            all_issues.extend(issues)
        warnings = [i for i in all_issues if i.severity == "warning"]
        assert not warnings, f"Factory dep key category mismatches: {[str(i) for i in warnings]}"

    def test_factory_has_llm_dep_keys(self):
        keys = get_factory_dep_keys()
        assert "llm" in keys
        assert "groq" in keys["llm"]
        assert "anthropic" in keys["llm"]

    def test_factory_has_vector_store_dep_keys(self):
        keys = get_factory_dep_keys()
        assert "vector_store" in keys
        assert "chroma" in keys["vector_store"]
        assert "pgvector" in keys["vector_store"]

    def test_factory_has_embedding_dep_keys(self):
        keys = get_factory_dep_keys()
        assert "embedding" in keys
        assert "ollama" in keys["embedding"]
        assert "fastembed" in keys["embedding"]

    def test_factory_has_reranker_dep_keys(self):
        keys = get_factory_dep_keys()
        assert "reranker" in keys
        assert "cohere" in keys["reranker"]
        assert "sentence_transformer" in keys["reranker"]
