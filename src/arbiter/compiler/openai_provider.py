"""Provider adapters; all API access stays outside the compiler core."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import openai
import requests
from openai import AzureOpenAI, OpenAI

from arbiter.compiler.models import CompilerDraft
from arbiter.compiler.prompts import SYSTEM_PROMPT


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
VERTEX_THINKING_BUDGET = 2_048
VERTEX_REQUEST_TIMEOUT_MS = 300_000


def _local_adc_access_token() -> str:
    """Read a short-lived local ADC token without ever persisting or logging it.

    The Google SDK normally refreshes ADC itself. Some Windows local environments
    can stall while that SDK refreshes its user credential; asking the installed
    gcloud CLI for the already-authenticated, short-lived token keeps the Vertex
    compiler run bounded. Production workloads should use their attached service
    identity rather than this local-only compiler adapter.
    """
    candidates = [shutil.which("gcloud")]
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            str(
                Path(local_app_data)
                / "Google"
                / "Cloud SDK"
                / "google-cloud-sdk"
                / "bin"
                / "gcloud.cmd"
            )
        )
    for command in dict.fromkeys(candidate for candidate in candidates if candidate):
        if not Path(command).is_file() and shutil.which(command) is None:
            continue
        try:
            completed = subprocess.run(
                [command, "auth", "application-default", "print-access-token", "--quiet"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        token = completed.stdout.strip()
        if token:
            return token
    raise RuntimeError(
        "Vertex requires a local Application Default Credential. Run "
        "gcloud auth application-default login and retry."
    )


class ProviderResponseError(RuntimeError):
    """A provider response that must be preserved beside the failed trial."""

    def __init__(self, message: str, response_artifact: dict[str, Any] | None = None):
        super().__init__(message)
        self.response_artifact = response_artifact


def resolve_provider(explicit: str | None = None) -> str:
    """Decide which provider a run targets, refusing to guess when several are configured.

    The preregistered protocol targets OpenAI. A leftover AZURE_API_BASE must
    never quietly redirect a run, so an ambiguous environment is an error rather
    than a default.
    """
    if explicit:
        return explicit
    configured = []
    if os.getenv("AZURE_API_BASE") and os.getenv("AZURE_API_KEY"):
        configured.append("azure")
    if os.getenv("OPENAI_API_KEY"):
        configured.append("openai")
    if os.getenv("OPENROUTER_API_KEY"):
        configured.append("openrouter")
    if len(configured) > 1:
        raise RuntimeError(
            f"Multiple providers are configured ({', '.join(configured)}). Pass --provider "
            "openai, azure, or openrouter so the target is explicit and recorded."
        )
    return configured[0] if configured else "openai"


def _response_artifact(response: Any) -> dict[str, Any] | None:
    """Serialize an SDK response only for an auditable failure artifact."""
    if response is None:
        return None
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except (TypeError, ValueError):
            pass
    return {"repr": repr(response)}


def build_client(provider: str | None = None) -> tuple[OpenAI | AzureOpenAI, str]:
    """Return the configured client and the provider name recorded in run metadata.

    On Azure the `model` argument is a deployment name, not a model identifier,
    so the two need not match. See docs/day6/COMPILER-IMPLEMENTATION.md.
    """
    resolved = resolve_provider(provider)
    if resolved == "openai":
        return OpenAI(), "openai"
    if resolved == "openrouter":
        return (
            OpenAI(
                api_key=os.environ["OPENROUTER_API_KEY"],
                base_url=OPENROUTER_BASE_URL,
            ),
            "openrouter",
        )
    return (
        AzureOpenAI(
            api_key=os.environ["AZURE_API_KEY"],
            azure_endpoint=os.environ["AZURE_API_BASE"],
            api_version=os.getenv("AZURE_API_VERSION", "2025-03-01-preview"),
        ),
        "azure",
    )


def _run_openrouter_extraction(
    *,
    model: str,
    reasoning_effort: str,
    user_prompt: str,
) -> tuple[CompilerDraft, dict[str, Any], dict[str, Any]]:
    """Extract through one forced tool call, then enforce the Pydantic contract locally.

    Nemotron 3 Ultra's free endpoint advertises tool calling but not native JSON-schema
    response formatting. The forced call is therefore transport, not validation: bad or
    incomplete arguments fail the trial and are never repaired or selectively retried.
    """
    started = datetime.now(UTC).isoformat()
    before = time.monotonic()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 30000,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "submit_compiler_draft",
                    "description": (
                        "Submit the complete evidence-bearing plan compiler draft. "
                        "Call this function exactly once."
                    ),
                    "parameters": CompilerDraft.model_json_schema(),
                },
            }
        ],
        "tool_choice": {
            "type": "function",
            "function": {"name": "submit_compiler_draft"},
        },
        "reasoning": {"effort": reasoning_effort},
        "provider": {"require_parameters": True},
    }
    try:
        http_response = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                "Content-Type": "application/json",
                "X-Title": "Arbiter Dental Compiler",
            },
            json=payload,
            timeout=(20, 600),
        )
        response = http_response.json()
    except requests.RequestException as exc:
        raise ProviderResponseError(f"OpenRouter request error: {exc}") from exc
    except ValueError as exc:
        raise ProviderResponseError(
            f"OpenRouter returned non-JSON HTTP {http_response.status_code}",
            {"http_status": http_response.status_code, "body": http_response.text},
        ) from exc
    latency_ms = round((time.monotonic() - before) * 1000)
    if not http_response.ok:
        raise ProviderResponseError(
            f"OpenRouter HTTP {http_response.status_code}",
            {"http_status": http_response.status_code, "response": response},
        )
    try:
        calls = [
            call
            for call in response["choices"][0]["message"].get("tool_calls", [])
            if call.get("function", {}).get("name") == "submit_compiler_draft"
        ]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderResponseError(
            "OpenRouter response omitted the expected chat-completion tool-call shape",
            response,
        ) from exc
    if len(calls) != 1:
        raise ProviderResponseError(
            "OpenRouter compiler response must contain exactly one submit_compiler_draft "
            f"tool call; received {len(calls)}",
            response,
        )
    # Parse once to distinguish malformed JSON in the failure ledger, then let Pydantic
    # enforce the complete semantic shape. Neither step modifies model output.
    arguments = calls[0]["function"].get("arguments")
    if not isinstance(arguments, str):
        raise ProviderResponseError(
            "OpenRouter tool call omitted string arguments",
            response,
        )
    try:
        json.loads(arguments)
        draft = CompilerDraft.model_validate_json(arguments)
    except (ValueError, TypeError) as exc:
        raise ProviderResponseError(
            f"OpenRouter tool arguments failed local validation: {exc}",
            response,
        ) from exc
    metadata = {
        "provider": "openrouter",
        "transport": "chat_completions_forced_tool",
        "schema_enforcement": "local_pydantic_no_repair",
        "sdk_version": openai.__version__,
        "model_requested": model,
        "model_returned": response.get("model"),
        "reasoning_effort": reasoning_effort,
        "temperature": None,
        "max_tokens": 30000,
        "started_at": started,
        "latency_ms": latency_ms,
        "response_id": response.get("id"),
        "usage": response.get("usage"),
    }
    return draft, response, metadata


def _run_vertex_extraction(
    *,
    model: str,
    reasoning_effort: str,
    user_prompt: str,
    project: str,
    location: str,
) -> tuple[CompilerDraft, dict[str, Any], dict[str, Any]]:
    """Use Vertex AI through local ADC and reject malformed JSON locally.

    The caller's Google identity is loaded by the Google SDK from ADC. No API
    key, service-account JSON, or credential value passes through ARBITER.
    """
    try:
        from google import genai
        from google.genai import types
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover - exercised in real setup only
        raise RuntimeError(
            "Vertex provider requires google-genai. Install project dependencies first."
        ) from exc

    started = datetime.now(UTC).isoformat()
    before = time.monotonic()
    response: Any = None
    try:
        # Keep the token in memory only. See _local_adc_access_token() for why
        # this local benchmark path asks the installed gcloud CLI for it.
        client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=Credentials(token=_local_adc_access_token()),
        )
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_json_schema=CompilerDraft.model_json_schema(),
                temperature=0,
                max_output_tokens=16_000,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=VERTEX_THINKING_BUDGET
                ),
                http_options=types.HttpOptions(timeout=VERTEX_REQUEST_TIMEOUT_MS),
            ),
        )
        response_text = response.text
        if not response_text:
            raise ProviderResponseError(
                "Vertex returned no text for the compiler draft", _response_artifact(response)
            )
        draft = CompilerDraft.model_validate_json(response_text)
    except ProviderResponseError:
        raise
    except Exception as exc:
        raise ProviderResponseError(
            f"Vertex compiler response failed validation: {exc}", _response_artifact(response)
        ) from exc

    latency_ms = round((time.monotonic() - before) * 1000)
    raw = _response_artifact(response) or {}
    usage = _response_artifact(getattr(response, "usage_metadata", None))
    metadata = {
        "provider": "vertex",
        "transport": "vertex_generate_content_json_schema",
        "schema_enforcement": "vertex_json_schema_and_local_pydantic_no_repair",
        "sdk_version": getattr(genai, "__version__", None),
        "model_requested": model,
        "model_returned": getattr(response, "model_version", None),
        "reasoning_effort": reasoning_effort,
        "temperature": 0,
        "max_output_tokens": 16_000,
        "thinking_budget": VERTEX_THINKING_BUDGET,
        "request_timeout_ms": VERTEX_REQUEST_TIMEOUT_MS,
        "vertex_project": project,
        "vertex_location": location,
        "started_at": started,
        "latency_ms": latency_ms,
        "response_id": getattr(response, "response_id", None),
        "usage": usage,
    }
    return draft, raw, metadata


def run_openai_extraction(
    *,
    model: str,
    reasoning_effort: str,
    user_prompt: str,
    provider: str | None = None,
) -> tuple[CompilerDraft, dict[str, Any], dict[str, Any]]:
    provider = resolve_provider(provider)
    if provider == "openrouter":
        return _run_openrouter_extraction(
            model=model,
            reasoning_effort=reasoning_effort,
            user_prompt=user_prompt,
        )
    client, provider = build_client(provider)
    started = datetime.now(UTC).isoformat()
    before = time.monotonic()
    response = client.responses.parse(
        model=model,
        reasoning={"effort": reasoning_effort},
        max_output_tokens=30000,
        store=False,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        text_format=CompilerDraft,
    )
    latency_ms = round((time.monotonic() - before) * 1000)
    if response.output_parsed is None:
        raise RuntimeError("model returned no parsed compiler draft")
    metadata = {
        "provider": provider,
        "sdk_version": openai.__version__,
        "model_requested": model,
        "model_returned": response.model,
        "reasoning_effort": reasoning_effort,
        "temperature": None,
        "max_output_tokens": 30000,
        "store": False,
        "started_at": started,
        "latency_ms": latency_ms,
        "response_id": response.id,
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
    }
    return response.output_parsed, response.model_dump(mode="json"), metadata


def run_compiler_extraction(
    *,
    model: str,
    reasoning_effort: str,
    user_prompt: str,
    provider: str | None = None,
    vertex_project: str | None = None,
    vertex_location: str = "global",
) -> tuple[CompilerDraft, dict[str, Any], dict[str, Any]]:
    """Dispatch to an explicitly selected provider without weakening validation."""
    resolved = resolve_provider(provider)
    if resolved == "vertex":
        if not vertex_project:
            raise RuntimeError(
                "Vertex requires --vertex-project or GOOGLE_CLOUD_PROJECT; ADC alone "
                "does not declare the billing/quota project."
            )
        return _run_vertex_extraction(
            model=model,
            reasoning_effort=reasoning_effort,
            user_prompt=user_prompt,
            project=vertex_project,
            location=vertex_location,
        )
    return run_openai_extraction(
        model=model,
        reasoning_effort=reasoning_effort,
        user_prompt=user_prompt,
        provider=resolved,
    )
