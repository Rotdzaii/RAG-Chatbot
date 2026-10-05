from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


QUERY_PROCESSING_MODEL = "gemini-3.8-flash"
HISTORY_MAX_TURNS = 6
HISTORY_MAX_MESSAGES = HISTORY_MAX_TURNS * 2
HISTORY_MAX_CHARACTERS = 6000

QUERY_PROCESSING_SYSTEM_INSTRUCTION = """Resolve the user's current question for a university-program and
academic-affairs RAG assistant. Return only the requested structured result.

Choose action=search when the current question is already standalone or when the
conversation history supplies enough information to make it standalone. Put the
resolved question in standalone_query, in the same language as the user.

If the current question is already clear and standalone, preserve it unchanged.
When resolving a follow-up, add only the missing subject or referent needed to make
the question standalone. Preserve every existing constraint from the current
question, including references to a named source or document section, time period,
audience, comparison, negation, and requested scope. Do not paraphrase away such
qualifiers or broaden or narrow the request.

Choose action=clarify when an essential subject or intent is missing and cannot be
resolved from history. Put one concise clarification question in clarification.

The current question has priority when the user changes topic. Never force a new
topic back to an older subject. Do not invent a subject, program, policy, or fact.
Conversation history is only for resolving references and intent; it is not
academic evidence and must not be copied as a factual answer. Do not answer the
academic question itself."""


class QueryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["search", "clarify"]
    standalone_query: str | None = None
    clarification: str | None = None

    @model_validator(mode="after")
    def validate_action_payload(self) -> "QueryDecision":
        if self.action == "search":
            if self.standalone_query is None or not self.standalone_query.strip():
                raise ValueError("search requires standalone_query")
            self.standalone_query = self.standalone_query.strip()
            self.clarification = None
        else:
            if self.clarification is None or not self.clarification.strip():
                raise ValueError("clarify requires clarification")
            self.clarification = self.clarification.strip()
            self.standalone_query = None
        return self


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class QueryProcessingResult:
    action: Literal["search", "clarify"]
    standalone_query: str | None
    clarification: str | None
    history_used: bool
    elapsed_ms: float


def query_processing_config() -> dict[str, object]:
    return {
        "enabled": True,
        "provider": "gemini",
        "model": QUERY_PROCESSING_MODEL,
        "actions": ["search", "clarify"],
        "structured_output": "QueryDecision",
        "structured_output_method": "json_schema",
        "structured_output_include_raw": False,
        "request_timeout_seconds": None,
        "provider_retry_attempts": 6,
        "provider_runtime_defaults_from": "langchain-google-genai 4.4.0",
        "system_instruction_sha256": hashlib.sha256(
            QUERY_PROCESSING_SYSTEM_INSTRUCTION.encode("utf-8")
        ).hexdigest(),
        "history_max_turns": HISTORY_MAX_TURNS,
        "history_max_messages": HISTORY_MAX_MESSAGES,
        "history_max_characters": HISTORY_MAX_CHARACTERS,
        "history_used_for_rag": True,
        "query_rewriting": True,
        "rewritten_query": "per_request",
        "configured_from": (
            "backend/rag/query_contract.py, backend/rag/query_processing.py, "
            "backend/rag/qa.py and backend/rag/router.py"
        ),
    }
