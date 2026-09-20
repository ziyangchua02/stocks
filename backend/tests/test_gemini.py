import json

import httpx
import pytest

from app.providers.common import ProviderError
from app.providers.gemini import Gemini, generation_schema
from app.services.news_analysis import SCHEMA
from app.settings import NewsAnalysisConfig


def test_schema_uses_supported_subset_without_weakening_local_validation():
    schema = generation_schema(SCHEMA)
    encoded = json.dumps(schema)
    for unsupported in ("$ref", "$defs", "exclusiveMinimum", "minLength", "maxItems"):
        assert unsupported not in encoded
    assert schema["properties"]["impact"]["enum"] == ["low", "medium", "high"]
    assert "evidence" in schema["required"]
    assert "maxItems" in json.dumps(SCHEMA)  # strict application schema is untouched


async def test_rest_contract_header_and_structured_json():
    async def handler(request):
        assert request.headers["x-goog-api-key"] == "secret-test"
        assert "secret-test" not in str(request.url)
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["responseJsonSchema"]["required"]
        assert "tools" not in body
        assert body["systemInstruction"]["parts"][0]["text"] == "instruction"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"thought": True, "text": "Do not expose internal thought"},
                                {"text": "{}"},
                            ]
                        },
                    }
                ],
                "usageMetadata": {"totalTokenCount": 42, "privateField": "ignored"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gemini = Gemini("secret-test", NewsAnalysisConfig(), client)
        result = await gemini.generate("instruction", "input", SCHEMA)
        assert result == {"text": "{}", "usage": {"totalTokenCount": 42}}


@pytest.mark.parametrize(
    "code,error",
    [
        (400, "http_400"),
        (401, "unauthorized_or_plan_restricted"),
        (403, "unauthorized_or_plan_restricted"),
        (404, "model_unavailable"),
        (429, "rate_limited"),
        (503, "provider_server_error"),
        (302, "http_302"),
    ],
)
async def test_http_errors_are_sanitized_and_not_followed(code, error):
    async def handler(request):
        return httpx.Response(
            code, headers={"Retry-After": "123"}, json={"error": {"message": "secret-test"}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gemini = Gemini("secret-test", NewsAnalysisConfig(), client)
        with pytest.raises(ProviderError) as caught:
            await gemini.generate("system", "input", SCHEMA)
        assert str(caught.value) == error
        if code == 429:
            assert caught.value.retry_seconds == 123


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"promptFeedback": {"blockReason": "SAFETY"}}, "blocked_or_empty_response"),
        ({"candidates": [{"finishReason": "MAX_TOKENS"}]}, "incomplete_or_blocked_response"),
        (
            {"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]},
            "blocked_or_empty_response",
        ),
    ],
)
async def test_safety_and_truncated_output_are_not_valid_analysis(payload, error):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        gemini = Gemini("secret-test", NewsAnalysisConfig(), client)
        assert (await gemini.generate("system", "input", SCHEMA))["error"] == error
