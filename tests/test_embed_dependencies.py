"""Missing optional dependency guidance without downloading models or hiding broken installs."""

import builtins

import pytest

from app.embed import _model, embed


@pytest.mark.parametrize("missing", ["sentence_transformers", "torch"])
def test_missing_real_embedding_dependency(monkeypatch, missing):
    original = builtins.__import__

    def import_module(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ModuleNotFoundError(f"No module named {missing!r}", name=missing)
        return original(name, *args, **kwargs)

    _model.cache_clear()
    monkeypatch.setattr(builtins, "__import__", import_module)
    monkeypatch.setenv("RAG_MODE", "real")
    if missing == "sentence_transformers":
        with pytest.raises(
            RuntimeError, match="python -m pip install -r requirements-real.txt"
        ) as exc:
            embed(["hello"])
        assert isinstance(exc.value.__cause__, ModuleNotFoundError)
    else:
        with pytest.raises(ModuleNotFoundError) as exc:
            embed(["hello"])
        assert exc.value.name == "torch"


def test_mock_embeddings_do_not_import_optional_model_package(monkeypatch):
    original = builtins.__import__

    def import_module(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise AssertionError("Mock mode must not import optional real dependencies")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_module)
    assert embed(["hello"]).shape == (1, 384)
