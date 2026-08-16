"""SuperInvesting (private Expo web app) client — personal-use only.

This is reverse-engineered, not a public API. Prefer checking ToS before shipping.
Token is stored in app_settings (never logged). JWT typically lasts ~3 days.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE = "https://superinvesting.ai"
QUERY_BASE = "https://query.superinvesting.ai"
STARTERS_BASE = "https://api.thefuture.university"

CHAT_TIMEOUT = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)
DEFAULT_TIMEOUT = httpx.Timeout(30.0)


class SuperInvestingError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SuperInvestingService:
    def __init__(self, token: str):
        token = (token or "").strip()
        if not token:
            raise SuperInvestingError("Fundamental Analyst Bearer token is required. Save one at the top of Investing Agent.")
        self.token = token
        self._auth_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }

    async def create_conversation(self, message: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{BASE}/api/v3/conversation",
                headers=self._auth_headers,
                json={"initialMessage": message},
            )
        self._raise_for_status(resp, "create conversation")
        data = resp.json()
        cid = data.get("id")
        if not cid:
            raise SuperInvestingError("Conversation create returned no id")
        return data

    async def stream_chat_events(
        self,
        conversation_id: str,
        message: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield parsed Vercel AI SDK UI stream events from /api/v2/chat."""
        body = {
            "id": conversation_id,
            "messages": [
                {"role": "user", "parts": [{"type": "text", "text": message}]},
            ],
            "trigger": "submit-message",
        }
        url = f"{BASE}/api/v2/chat?conversationId={conversation_id}"
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
            async with client.stream(
                "POST",
                url,
                headers=self._auth_headers,
                json=body,
            ) as resp:
                if resp.status_code == 403:
                    raise SuperInvestingError(
                        "Feature usage limit reached (403). Try again later or check your Fundamental Analyst plan.",
                        status_code=403,
                    )
                if resp.status_code >= 400:
                    text = ""
                    try:
                        text = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                    except Exception:
                        pass
                    raise SuperInvestingError(
                        f"Chat stream failed ({resp.status_code}): {text or resp.reason_phrase}",
                        status_code=resp.status_code,
                    )
                async for line in resp.aiter_lines():
                    line = (line or "").strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                        if not payload or payload == "[DONE]":
                            continue
                        try:
                            yield json.loads(payload)
                        except json.JSONDecodeError:
                            continue

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(
                f"{BASE}/api/v2/conversation",
                headers=self._auth_headers,
                params={"id": conversation_id},
            )
        self._raise_for_status(resp, "get conversation")
        return resp.json()

    async def analyze_once(self, message: str) -> dict[str, Any]:
        """Full non-streaming flow: create → drain chat stream → read conversation."""
        created = await self.create_conversation(message)
        cid = str(created["id"])
        text_buf: list[str] = []
        tools_seen: set[str] = set()
        async for raw in self.stream_chat_events(cid, message):
            summarized = self.summarize_stream_event(raw)
            if not summarized:
                continue
            if summarized["kind"] == "text":
                text_buf.append(summarized["text"])
            elif summarized["kind"] == "tool":
                tool = summarized.get("tool") or ""
                if tool:
                    tools_seen.add(str(tool))
        conversation = await self.get_conversation(cid)
        answer = self.extract_assistant_markdown(conversation)
        if not answer and text_buf:
            answer = "".join(text_buf)
        return {
            "conversation_id": cid,
            "answer": answer,
            "tools": sorted(tools_seen),
        }

    async def stock_card(self, symbol: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(
                f"{BASE}/api/stock/card",
                headers=self._auth_headers,
                params={"symbol": symbol.upper()},
            )
        self._raise_for_status(resp, "stock card")
        return resp.json()

    async def stock_detail(self, symbol: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{BASE}/api/v3/stock",
                headers=self._auth_headers,
                json={"symbol": symbol.upper()},
            )
        self._raise_for_status(resp, "stock detail")
        return resp.json()

    async def stock_search(self, query: str, page: int = 1, limit: int = 20) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(
                f"{BASE}/api/search",
                headers=self._auth_headers,
                params={"query": query, "page": page, "limit": limit},
            )
        self._raise_for_status(resp, "stock search")
        return resp.json()

    async def fuzzy_ticker_match(
        self,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.5,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{QUERY_BASE}/tool/fuzzy-ticker-match",
                headers={"Content-Type": "application/json"},
                json={"query": query, "limit": limit, "minSimilarity": min_similarity},
            )
        self._raise_for_status(resp, "fuzzy ticker match")
        return resp.json()

    @staticmethod
    async def fetch_starters() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(f"{STARTERS_BASE}/key-value/STOX_AI_STARTERS")
        if resp.status_code >= 400:
            return {"value": None}
        return resp.json()

    @staticmethod
    def extract_assistant_markdown(conversation: dict[str, Any]) -> str:
        messages = conversation.get("messages") or []
        for msg in reversed(messages):
            role = str(msg.get("role") or "").upper()
            if role == "ASSISTANT":
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            parts.append(str(part.get("text") or ""))
                        elif isinstance(part, str):
                            parts.append(part)
                    joined = "".join(parts).strip()
                    if joined:
                        return joined
        return ""

    @staticmethod
    def summarize_stream_event(event: dict[str, Any]) -> dict[str, Any] | None:
        """Map raw AI SDK events into compact UI-friendly chunks."""
        etype = str(event.get("type") or "")
        if etype in ("start", "start-step", "finish-step", "finish", "message-metadata"):
            return {"kind": "status", "type": etype}
        if etype in ("reasoning-delta", "reasoning"):
            delta = event.get("delta") or event.get("textDelta") or event.get("text") or ""
            if delta:
                return {"kind": "reasoning", "text": str(delta)}
            return None
        if etype.startswith("tool-"):
            tool_name = (
                event.get("toolName")
                or event.get("toolCallName")
                or event.get("name")
                or ""
            )
            return {
                "kind": "tool",
                "type": etype,
                "tool": str(tool_name),
                "toolCallId": event.get("toolCallId") or event.get("id"),
            }
        if etype in ("text-delta", "text"):
            delta = event.get("delta") or event.get("textDelta") or event.get("text") or ""
            if delta:
                return {"kind": "text", "text": str(delta)}
            return None
        if etype == "error":
            return {"kind": "error", "message": str(event.get("errorText") or event.get("message") or event)}
        return None

    def _raise_for_status(self, resp: httpx.Response, action: str) -> None:
        if resp.status_code == 401:
            raise SuperInvestingError(
                "Fundamental Analyst token rejected (401). Paste a fresh JWT from the Fundamental Analyst app (OTP login).",
                status_code=401,
            )
        if resp.status_code == 403:
            raise SuperInvestingError(
                "Feature usage limit reached (403).",
                status_code=403,
            )
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.text[:400]
            except Exception:
                detail = resp.reason_phrase
            raise SuperInvestingError(
                f"Failed to {action} ({resp.status_code}): {detail}",
                status_code=resp.status_code,
            )


async def run_analysis_stream(token: str, message: str) -> AsyncIterator[str]:
    """Yield SSE lines for the frontend: status / reasoning / tool / text / done / error."""

    def _sse(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    try:
        svc = SuperInvestingService(token)
        yield _sse({"kind": "status", "message": "Creating conversation…"})
        created = await svc.create_conversation(message)
        cid = created["id"]
        yield _sse({"kind": "conversation", "id": cid, "value": created.get("value") or message})

        yield _sse({"kind": "status", "message": "Streaming analysis (may take 1–2 min)…"})
        text_buf: list[str] = []
        reasoning_buf: list[str] = []
        tools_seen: set[str] = set()

        async for raw in svc.stream_chat_events(cid, message):
            summarized = SuperInvestingService.summarize_stream_event(raw)
            if not summarized:
                continue
            if summarized["kind"] == "text":
                text_buf.append(summarized["text"])
            elif summarized["kind"] == "reasoning":
                reasoning_buf.append(summarized["text"])
            elif summarized["kind"] == "tool":
                tool = summarized.get("tool") or ""
                if tool and tool not in tools_seen:
                    tools_seen.add(tool)
            yield _sse(summarized)

        yield _sse({"kind": "status", "message": "Fetching saved conversation…"})
        conversation = await svc.get_conversation(cid)
        answer = SuperInvestingService.extract_assistant_markdown(conversation)
        if not answer and text_buf:
            answer = "".join(text_buf)

        yield _sse(
            {
                "kind": "done",
                "conversation_id": cid,
                "answer": answer,
                "reasoning": "".join(reasoning_buf).strip() or None,
                "tools": sorted(tools_seen),
            }
        )
    except SuperInvestingError as exc:
        yield _sse({"kind": "error", "message": str(exc), "status_code": exc.status_code})
    except httpx.TimeoutException:
        yield _sse({"kind": "error", "message": "Fundamental Analyst request timed out (limit 180s). Try again."})
    except Exception as exc:
        logger.exception("SuperInvesting analysis failed")
        yield _sse({"kind": "error", "message": f"Unexpected error: {exc}"})


def analyze_message_sync(token: str, message: str) -> str:
    """Sync wrapper for Ask AI / call_ai_report when provider is Investing Agent."""
    try:
        svc = SuperInvestingService(token)
        with httpx.Client(timeout=CHAT_TIMEOUT) as client:
            resp = client.post(
                f"{BASE}/api/v3/conversation",
                headers=svc._auth_headers,
                json={"initialMessage": message},
            )
            if resp.status_code == 401:
                return "Fundamental Analyst token rejected (401). Paste a fresh JWT in Manage → AI Settings."
            if resp.status_code == 403:
                return "Feature usage limit reached (403)."
            if resp.status_code >= 400:
                return f"Failed to create conversation ({resp.status_code}): {resp.text[:300]}"
            cid = resp.json().get("id")
            if not cid:
                return "Conversation create returned no id."

            body = {
                "id": cid,
                "messages": [{"role": "user", "parts": [{"type": "text", "text": message}]}],
                "trigger": "submit-message",
            }
            text_buf: list[str] = []
            with client.stream(
                "POST",
                f"{BASE}/api/v2/chat?conversationId={cid}",
                headers=svc._auth_headers,
                json=body,
            ) as stream:
                if stream.status_code == 403:
                    return "Feature usage limit reached (403)."
                if stream.status_code >= 400:
                    detail = stream.read().decode("utf-8", errors="replace")[:300]
                    return f"Chat stream failed ({stream.status_code}): {detail}"
                for line in stream.iter_lines():
                    line = (line or "").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    summarized = SuperInvestingService.summarize_stream_event(event)
                    if summarized and summarized["kind"] == "text":
                        text_buf.append(summarized["text"])

            conv = client.get(
                f"{BASE}/api/v2/conversation",
                headers=svc._auth_headers,
                params={"id": cid},
            )
            if conv.status_code >= 400:
                if text_buf:
                    return "".join(text_buf)
                return f"Failed to load conversation ({conv.status_code})"
            answer = SuperInvestingService.extract_assistant_markdown(conv.json())
            return answer or "".join(text_buf) or "No assistant reply returned."
    except SuperInvestingError as exc:
        return str(exc)
    except httpx.TimeoutException:
        return "Fundamental Analyst request timed out (limit 180s). Try again."
    except Exception as exc:
        logger.exception("SuperInvesting sync analyze failed")
        return f"AI report error: {exc}. Check Fundamental Analyst token in Manage settings."
