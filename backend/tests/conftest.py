import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def force_sqlite_mode(monkeypatch):
    from config import settings

    # Unit tests default to SQLite even when CI exports SUPABASE_DB_URL.
    # Tests that need Postgres behavior can override this per-test.
    monkeypatch.setattr(settings, "supabase_db_url", "")


@pytest.fixture(autouse=True)
def block_live_llm_credentials(monkeypatch):
    from config import settings

    # Test code must use fakes/mocks for model calls. This prevents a local
    # shell with real API keys from leaking paid credentials into pytest.
    monkeypatch.setattr(settings, "anthropic_api_key", "test-disabled")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "moonshot_api_key", "")


@pytest.fixture(autouse=True)
def skip_prompt_injection_model(monkeypatch):
    from agent.stream_utils import StructuredLLMResponse

    # Dedicated guard tests restore real scanning and provide explicit model responses.
    monkeypatch.setattr("api.chat_guards.check_prompt_injection", lambda _text: True)
    monkeypatch.setattr("api.sse_handler.check_prompt_injection", lambda _text: True)

    monkeypatch.setattr(
        "api.chat_guards.stream_structured_llm",
        AsyncMock(
            return_value=StructuredLLMResponse(
                text=json.dumps({"verdict": "ACCEPT"}),
                finish_reason="end_turn",
                input_tokens=1,
                output_tokens=1,
                provider="anthropic",
                model="claude-opus-5",
            )
        ),
    )


@pytest.fixture(autouse=True)
def clear_rate_limits():
    from adapters.database_adapter import execute

    try:
        execute("DELETE FROM rate_limit_events")
        execute("DELETE FROM request_events")
        execute("DELETE FROM product_analytics_events")
        execute("DELETE FROM search_tool_requests")
        execute("DELETE FROM active_streams")
        execute("DELETE FROM http_request_logs")
        execute("DELETE FROM llm_telemetry")
        execute("DELETE FROM analytics_events")
    except Exception:
        pass
    yield
    try:
        execute("DELETE FROM rate_limit_events")
        execute("DELETE FROM request_events")
        execute("DELETE FROM product_analytics_events")
        execute("DELETE FROM search_tool_requests")
        execute("DELETE FROM active_streams")
        execute("DELETE FROM http_request_logs")
        execute("DELETE FROM llm_telemetry")
        execute("DELETE FROM analytics_events")
    except Exception:
        pass
