import pytest

from mem0.utils.optional_deps import (
    DepInfo,
    build_factory_dep_keys,
    get_all_providers,
    get_dep_info,
    make_import_error,
    run_validation,
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
            factory_name="test",
        )
        with pytest.raises(AttributeError):
            info.provider = "changed"

    def test_dep_info_with_none_factory_name(self):
        info = DepInfo(
            provider="test",
            category="nlp",
            import_packages=["test_pkg"],
            extras=None,
            pip_packages=["test-pkg"],
            factory_name=None,
        )
        assert info.factory_name is None


class TestRegistryBasics:
    def test_get_dep_info_exists(self):
        info = get_dep_info("groq")
        assert info is not None
        assert info.provider == "groq"
        assert info.category == "llm"
        assert "groq" in info.import_packages
        assert info.extras == "llms"
        assert info.factory_name == "groq"

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


class TestFactoryNameAutoDerive:
    def test_build_factory_dep_keys_returns_mapping(self):
        keys = build_factory_dep_keys()
        assert isinstance(keys, dict)
        assert "llm" in keys
        assert "embedding" in keys
        assert "vector_store" in keys
        assert "reranker" in keys

    def test_same_factory_name_different_categories(self):
        keys = build_factory_dep_keys()
        assert keys["llm"]["ollama"] == "ollama"
        assert keys["embedding"]["ollama"] == "ollama_emb"

    def test_factory_name_to_dep_key_mapping(self):
        keys = build_factory_dep_keys()
        assert keys["reranker"]["cohere"] == "cohere_reranker"
        assert keys["reranker"]["huggingface"] == "huggingface_reranker"
        assert keys["vector_store"]["redis"] == "redis_vs"
        assert keys["vector_store"]["elasticsearch"] == "elasticsearch_vs"

    def test_no_factory_name_excluded(self):
        keys = build_factory_dep_keys()
        all_dep_keys = {dk for m in keys.values() for dk in m.values()}
        assert "qdrant_extra" not in all_dep_keys
        assert "spacy" not in all_dep_keys


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
    def test_all_factory_dep_keys_valid(self):
        keys = build_factory_dep_keys()
        issues = validate_factory_dep_keys(keys)
        errors = [i for i in issues if i.severity == "error"]
        assert not errors, f"Factory dep key errors: {[str(i) for i in errors]}"

    def test_all_factory_dep_keys_category_match(self):
        keys = build_factory_dep_keys()
        issues = validate_factory_dep_keys(keys)
        warnings = [i for i in issues if i.severity == "warning"]
        assert not warnings, f"Factory dep key category mismatches: {[str(i) for i in warnings]}"


class TestRunValidation:
    def test_run_validation_passes(self):
        issues = run_validation()
        assert not issues, f"Validation issues: {[str(i) for i in issues]}"

    def test_run_validation_catches_errors(self):
        from mem0.utils import optional_deps
        original = dict(optional_deps._REGISTRY)
        optional_deps._REGISTRY["__test_bad"] = DepInfo(
            provider="__test_bad",
            category="llm",
            import_packages=["nonexistent_pkg"],
            extras="nonexistent-extras-group",
            pip_packages=["nonexistent-pkg"],
            factory_name=None,
        )
        try:
            issues = run_validation()
            errors = [i for i in issues if i.severity == "error"]
            assert errors
        finally:
            optional_deps._REGISTRY = original
