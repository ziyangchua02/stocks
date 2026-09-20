"""Gemini generateContent REST adapter. No SDK, tools, URL fetching, or key in URLs."""

import httpx

from app.providers.common import ProviderError, retry_delay


def generation_schema(schema):
    """Keep the portable generation subset; enforce all other constraints locally.

    Flatten Pydantic references and omit length/numeric bounds that Google's
    schema compiler can reject, especially on nested citation arrays.
    """

    def convert(node):
        if "$ref" in node:
            return convert(schema["$defs"][node["$ref"].rsplit("/", 1)[-1]])
        result = {key: node[key] for key in ("type", "enum", "required") if key in node}
        if "properties" in node:
            result["properties"] = {
                key: convert(value) for key, value in node["properties"].items()
            }
        if "items" in node:
            result["items"] = convert(node["items"])
        return result

    return convert(schema)


class Gemini:
    def __init__(self, key, config, client=None):
        self.key = key
        self.config = config
        self.configured = bool(key)
        self.client = client or httpx.AsyncClient(
            timeout=config.timeout_seconds, follow_redirects=False
        )

    async def generate(self, instruction, prompt, schema):
        if not self.configured:
            raise ProviderError("missing_gemini_key", 3600)
        try:
            response = await self.client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.config.model}:generateContent",
                headers={"x-goog-api-key": self.key},
                json={
                    "systemInstruction": {"parts": [{"text": instruction}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseJsonSchema": generation_schema(schema),
                        "maxOutputTokens": self.config.max_output_tokens,
                        "temperature": 0.2,
                        "candidateCount": 1,
                    },
                },
            )
        except httpx.RequestError:
            raise ProviderError("network_or_timeout") from None
        if response.status_code == 429:
            delay = retry_delay(response.headers.get("Retry-After"))
            # Google also puts a protobuf RetryInfo delay in JSON error details.
            try:
                for detail in response.json().get("error", {}).get("details", []):
                    if detail.get("@type", "").endswith("RetryInfo"):
                        delay = max(delay, float(detail["retryDelay"].removesuffix("s")))
            except (ValueError, TypeError, KeyError, AttributeError):
                pass
            raise ProviderError("rate_limited", max(60, delay))
        if response.status_code in {401, 403}:
            raise ProviderError("unauthorized_or_plan_restricted", 3600)
        if response.status_code == 404:
            raise ProviderError("model_unavailable", 3600)
        if response.status_code >= 500:
            raise ProviderError("provider_server_error")
        if response.status_code != 200:
            raise ProviderError(f"http_{response.status_code}", 3600)
        try:
            payload = response.json()
            usage = {
                key: value
                for key, value in payload.get("usageMetadata", {}).items()
                if key
                in {
                    "promptTokenCount",
                    "candidatesTokenCount",
                    "totalTokenCount",
                    "thoughtsTokenCount",
                    "cachedContentTokenCount",
                }
                and type(value) is int
                and value >= 0
            }
            candidates = payload.get("candidates", [])
            if payload.get("promptFeedback", {}).get("blockReason") or not candidates:
                return {"error": "blocked_or_empty_response", "usage": usage}
            candidate = candidates[0]
            if candidate.get("finishReason") != "STOP":
                return {"error": "incomplete_or_blocked_response", "usage": usage}
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(
                part["text"] for part in parts if "text" in part and not part.get("thought")
            )
            if not text.strip():
                return {"error": "blocked_or_empty_response", "usage": usage}
            return {"text": text, "usage": usage}
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderError("invalid_provider_response", 900) from None

    async def close(self):
        await self.client.aclose()
