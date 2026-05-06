"""Gateway model list URL derivation for /models/live."""
from app.services.model_registry import _llm_models_list_url


def test_llm_models_list_url_from_v1_chat_completions():
    assert (
        _llm_models_list_url("http://192.168.1.1:1234/v1/chat/completions")
        == "http://192.168.1.1:1234/v1/models"
    )


def test_llm_models_list_url_append_v1_models():
    assert _llm_models_list_url("https://api.example.com").endswith("/v1/models")
