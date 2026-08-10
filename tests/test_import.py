import ai_registry
from ai_registry import Registry


def test_package_exposes_registry_and_version() -> None:
    assert Registry is not None
    assert isinstance(ai_registry.__version__, str)
