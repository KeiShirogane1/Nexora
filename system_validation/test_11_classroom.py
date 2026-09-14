import importlib


def test_classroom_service_imports():
    module = importlib.import_module("app.Services.classroom_service")
    assert callable(module.ensure_classroom_schema)
