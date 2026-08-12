import ai_registry
from ai_registry import Registry


def test_package_exposes_registry_and_version() -> None:
    assert Registry is not None
    assert isinstance(ai_registry.__version__, str)


def test_package_exposes_client_factory() -> None:
    from ai_registry import ClientFactory

    assert ClientFactory is not None


def test_core_import_does_not_import_adapter_extras() -> None:
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import ai_registry, sys;"
            "assert 'ai_registry.adapters.openai' not in sys.modules;"
            "assert 'ai_registry.adapters.pydantic_ai' not in sys.modules",
        ],
        check=True,
    )
