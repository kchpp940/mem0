import pytest

from mem0.utils.optional_deps import (
    DepInfo,
    ValidationIssue,
    _class_exists_in_source,
    build_factory_dep_keys,
    get_all_providers,
    get_dep_info,
    make_import_error,
    optional_import,
    require_adapter_class,
    run_validation,
    validate_adapters,
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
            adapter_module="mem0.llms.test",
            adapter_class="TestLLM",
            adapter_class_path="mem0.llms.test.LLM",
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
            adapter_module=None,
            adapter_class=None,
            adapter_class_path=None,
        )
        assert info.factory_name is None
        assert info.adapter_module is None
        assert info.adapter_class is None
        assert info.adapter_class_path is None

    def test_dep_info_adapter_contract_fields(self):
        info = DepInfo(
            provider="test",
            category="embedding",
            import_packages=["test_pkg"],
            extras="llms",
            pip_packages=["test-pkg"],
            factory_name="test",
            adapter_module="mem0.embeddings.test",
            adapter_class="TestEmbedding",
            adapter_class_path="mem0.embeddings.test.TestEmbedding",
        )
        module_path, class_name = info.adapter_class_path.rsplit(".", 1)
        assert module_path == info.adapter_module
        assert class_name == info.adapter_class


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

    def test_provider_has_adapter_contract(self):
        info = get_dep_info("groq")
        assert info.adapter_module == "mem0.llms.groq"
        assert info.adapter_class == "GroqLLM"
        assert info.adapter_class_path == "mem0.llms.groq.GroqLLM"

    def test_adapter_class_path_matches_module_and_class(self):
        for name, info in get_all_providers().items():
            if info.adapter_class_path is None:
                continue
            assert info.adapter_module is not None
            assert info.adapter_class is not None
            expected = f"{info.adapter_module}.{info.adapter_class}"
            assert info.adapter_class_path == expected, (
                f"Provider {name}: adapter_class_path {info.adapter_class_path!r} does not match "
                f"adapter_module + adapter_class {expected!r}"
            )

    def test_factory_providers_have_adapter_contract(self):
        for name, info in get_all_providers().items():
            if info.factory_name is not None:
                assert info.adapter_module is not None, (
                    f"Provider {name} has factory_name but no adapter_module"
                )
                assert info.adapter_class is not None, (
                    f"Provider {name} has factory_name but no adapter_class"
                )
                assert info.adapter_class_path is not None, (
                    f"Provider {name} has factory_name but no adapter_class_path"
                )


class TestOptionalImportHelper:
    def test_optional_import_success(self):
        try:
            result = optional_import("groq")
        except ImportError:
            pytest.skip("groq not installed in test environment")
        else:
            assert result is None

    def test_optional_import_with_module_symbol(self):
        try:
            cohere = optional_import("cohere_reranker", "cohere")
        except ImportError:
            pytest.skip("cohere not installed in test environment")
        else:
            assert cohere is not None
            assert hasattr(cohere, "__path__")

    def test_optional_import_with_class_symbol(self):
        try:
            Client = optional_import("groq", "groq.Groq")
        except ImportError:
            pytest.skip("groq not installed in test environment")
        else:
            assert Client is not None
            assert isinstance(Client, type)

    def test_optional_import_missing_package_raises_registry_error(self):
        from mem0.utils import optional_deps as od

        original = dict(od._REGISTRY)
        fake_info = DepInfo(
            provider="__test_nonexistent",
            category="llm",
            import_packages=["this_package_definitely_does_not_exist_xyz123"],
            extras="llms",
            pip_packages=["nonexistent-pkg"],
            factory_name=None,
            adapter_module=None,
            adapter_class=None,
            adapter_class_path=None,
        )
        od._REGISTRY["__test_nonexistent"] = fake_info
        try:
            with pytest.raises(ImportError) as exc_info:
                optional_import("__test_nonexistent")
            msg = str(exc_info.value)
            assert "__test_nonexistent" in msg
            assert "nonexistent-pkg" in msg
        finally:
            od._REGISTRY = original

    def test_optional_import_unknown_key(self):
        with pytest.raises(ImportError, match="Unknown provider"):
            optional_import("not_a_real_dep_key_12345")


class TestClassExistsInSource:
    def test_class_exists_in_source_true(self):
        source = """
class MyClass:
    pass

def some_func():
    pass
"""
        assert _class_exists_in_source(source, "MyClass") is True

    def test_class_exists_in_source_false(self):
        source = """
def some_func():
    pass
"""
        assert _class_exists_in_source(source, "NonExistent") is False

    def test_class_exists_in_source_nested(self):
        source = """
class Outer:
    class Inner:
        pass
"""
        assert _class_exists_in_source(source, "Outer") is True
        assert _class_exists_in_source(source, "Inner") is True

    def test_class_exists_in_source_syntax_error(self):
        source = "class Broken: def"
        assert _class_exists_in_source(source, "Broken") is False

    def test_class_exists_in_source_unicode(self):
        source = 'class MyClass:\n    """测试类"""\n    pass'
        assert _class_exists_in_source(source, "MyClass") is True


class TestRequireAdapterClass:
    def test_require_adapter_class_success(self):
        try:
            cls = require_adapter_class("ollama")
        except ImportError:
            pytest.skip("ollama not installed in test environment")
        else:
            assert cls is not None
            assert cls.__name__ == "OllamaLLM"
            assert cls.__module__ == "mem0.llms.ollama"

    def test_require_adapter_class_unknown_key(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            require_adapter_class("not_a_real_key_12345")

    def test_require_adapter_class_no_contract(self):
        from mem0.utils import optional_deps as od

        original = dict(od._REGISTRY)
        fake_info = DepInfo(
            provider="__test_no_contract",
            category="llm",
            import_packages=["test_pkg"],
            extras=None,
            pip_packages=["test-pkg"],
            factory_name=None,
            adapter_module=None,
            adapter_class=None,
            adapter_class_path=None,
        )
        od._REGISTRY["__test_no_contract"] = fake_info
        try:
            with pytest.raises(ValueError, match="no adapter contract"):
                require_adapter_class("__test_no_contract")
        finally:
            od._REGISTRY = original

    def test_require_adapter_class_returns_type(self):
        try:
            cls = require_adapter_class("ollama_emb")
        except ImportError:
            pytest.skip("ollama not installed in test environment")
        else:
            assert isinstance(cls, type)
            assert hasattr(cls, "__init__")


class TestAdaptersUseOptionalImport:
    def test_adapters_use_optional_import_instead_of_try_except(self):
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        adapter_dirs = [
            repo_root / "mem0" / "llms",
            repo_root / "mem0" / "embeddings",
            repo_root / "mem0" / "vector_stores",
            repo_root / "mem0" / "reranker",
        ]
        files_with_old_pattern = []
        for d in adapter_dirs:
            for py_file in sorted(d.rglob("*.py")):
                try:
                    content = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if "raise make_import_error(" in content and py_file.name != "__init__.py":
                    rel = py_file.relative_to(repo_root)
                    files_with_old_pattern.append(str(rel))
        assert not files_with_old_pattern, (
            "These adapter files still use old try/except + make_import_error pattern "
            "(should use optional_import instead):\n  " + "\n  ".join(files_with_old_pattern)
        )

    def test_adapters_import_optional_import(self):
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        adapter_dirs = [
            repo_root / "mem0" / "llms",
            repo_root / "mem0" / "embeddings",
            repo_root / "mem0" / "vector_stores",
            repo_root / "mem0" / "reranker",
        ]
        files_missing_import = []
        for d in adapter_dirs:
            for py_file in sorted(d.rglob("*.py")):
                if py_file.name == "__init__.py":
                    continue
                try:
                    content = py_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if "optional_import(" in content and "from mem0.utils.optional_deps import optional_import" not in content:
                    rel = py_file.relative_to(repo_root)
                    files_missing_import.append(str(rel))
        assert not files_missing_import, (
            "These adapter files call optional_import() but don't import it:\n  " +
            "\n  ".join(files_missing_import)
        )


class TestAdapterContractValidation:
    def test_validate_adapters_no_errors(self):
        issues = validate_adapters()
        errors = [i for i in issues if i.severity == "error"]
        assert not errors, f"Adapter validation errors: {[str(i) for i in errors]}"

    def test_validate_adapters_no_warnings_strict(self):
        issues = validate_adapters()
        warnings = [i for i in issues if i.severity == "warning"]
        assert not warnings, f"Adapter validation warnings: {[str(i) for i in warnings]}"

    def test_adapter_files_exist_for_registry_entries(self):
        issues = validate_adapters()
        missing_file_errors = [i for i in issues if "adapter file missing" in i.message]
        assert not missing_file_errors

    def test_adapter_classes_exist_in_files(self):
        issues = validate_adapters()
        missing_class_errors = [i for i in issues if "not found in" in i.message and "class" in i.message]
        assert not missing_class_errors

    def test_no_unknown_make_import_error_keys(self):
        issues = validate_adapters()
        unknown_key_errors = [i for i in issues if "not registered" in i.message and "make_import_error" in i.message]
        assert not unknown_key_errors

    def test_no_unknown_optional_import_keys(self):
        issues = validate_adapters()
        unknown_key_errors = [i for i in issues if "not registered" in i.message and "optional_import" in i.message]
        assert not unknown_key_errors

    def test_factory_paths_match_registry(self):
        issues = validate_adapters()
        path_mismatches = [i for i in issues if "factory." in i.message and "points to" in i.message]
        assert not path_mismatches

    def test_validation_issue_str_format(self):
        issue = ValidationIssue("error", "provider_x", "something is wrong")
        s = str(issue)
        assert "[error]" in s
        assert "provider_x" in s
        assert "something is wrong" in s

    def test_validate_adapters_detects_missing_class(self):
        from mem0.utils import optional_deps as od
        original = dict(od._REGISTRY)
        fake_info = DepInfo(
            provider="__test_missing_class",
            category="llm",
            import_packages=["ollama"],
            extras="llms",
            pip_packages=["ollama"],
            factory_name="ollama",
            adapter_module="mem0.llms.ollama",
            adapter_class="NonExistentClass",
            adapter_class_path="mem0.llms.ollama.NonExistentClass",
        )
        od._REGISTRY["__test_missing_class"] = fake_info
        try:
            issues = validate_adapters()
            class_errors = [
                i for i in issues
                if "NonExistentClass" in str(i) and "not found" in str(i)
            ]
            assert class_errors
        finally:
            od._REGISTRY = original


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
            adapter_module=None,
            adapter_class=None,
            adapter_class_path=None,
        )
        try:
            issues = run_validation()
            errors = [i for i in issues if i.severity == "error"]
            assert errors
        finally:
            optional_deps._REGISTRY = original
