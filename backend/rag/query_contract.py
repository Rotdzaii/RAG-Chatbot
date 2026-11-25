from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


QUERY_PROCESSING_MODEL = "gemini-3.8-flash"
HISTORY_MAX_TURNS = 6
HISTORY_MAX_MESSAGES = HISTORY_MAX_TURNS * 2
HISTORY_MAX_CHARACTERS = 6000
MAX_MAJOR_QUERIES = 4
WEB_ANSWER_LABEL = "Thông tin cập nhật từ web"
ComparisonCriterion = Annotated[str, StringConstraints(
    strip_whitespace=True, min_length=1, max_length=160, pattern=r"^[^\[\]\r\n|]+$",
)]

QUERY_PROCESSING_SYSTEM_INSTRUCTION = """Resolve the user's current question for a university-program and
academic-affairs RAG assistant. Return only the requested structured result.

Choose action=search when the current question is already standalone or when the
conversation history supplies enough information to make it standalone. Put the
resolved question in standalone_query, in the same language as the user.
Set answer_language to the ISO 639-1 code of the current question's language.
For internal questions in a language other than Vietnamese, write the retrieval
query in Vietnamese in search_query, or in search_question for each major_queries
entry. Keep Vietnamese questions on the existing path by leaving these fields null.
Translate only the retrieval text, preserving every constraint and proper noun.

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
academic evidence. Do not carry past assistant claims or values into retrieval
queries as facts. Preserve the user's constraints. Do not answer the academic
question itself.

Set scope=inventory for a count or list of all distinct majors represented in
the available VLU documents (including "VLU hiện có bao nhiêu ngành?" and
"Cho tôi biết tổng số ngành bạn có thể trả lời"). This is
never a count of specializations, courses, or universities. If the user asks for a
subset by a criterion that the inventory cannot verify (e.g. majors offered in
a particular year), clarify the scope instead of supplying an unqualified total.

For facts specific to named majors, include one major_queries entry for EACH
requested major, even for a single major. Use its full name without the 'ngành'
prefix, using the official Vietnamese program name when the user names it in
translation, and a standalone question limited to that major. Preserve the criteria, qualifiers and
language in every part. For a comparison use scope=compare and ask about the
same comparison criteria for each major. Put up to four shared comparison criteria
in comparison_criteria in the user's language. If the user explicitly requests
more than four criteria, ask which to prioritize rather than silently dropping any.
Each criterion must retain its own
qualifiers (such as year or cohort). In each major's question state its shared
scope, source and constraints; the retriever will prepend each individual criterion.
Exclude incidental mentions and past
topics. If 'ngành đó' could refer to either of two majors, clarify instead of
choosing one. If more than four majors are requested, ask the user to narrow
the question.

Choose evidence scope independently of search success. VLU, its rules,
programs and questions about the user's documents always stay internal,
including follow-ups about these topics. Never put them in external_parts.
If uncertain whether a fact is internal, keep it internal. Set include_internal
to false only when the current question has no internal request. When it does,
standalone_query and the internal scope/major fields must cover only the
internal request. Group the internal comparison into that one request.

Put requests for stable public knowledge in external_parts as general.
Put public requests needing recent or real-time facts in web (weather, news,
current prices). For each external part, question must be one contiguous,
verbatim excerpt from the CURRENT user question. Never add facts, quotes from
history, document contents, or instructions to a tool. Use at most one general
and one web part. For any external request missing an explicit public subject,
weather location or other necessary detail, ask a short clarification in the
user's language. If only that part is ambiguous in a mixed request, use a
clarify part with the verbatim excerpt and clarification, and retain the other
parts. Use the top-level clarify action when there is nothing else to answer.
For fully internal requests leave external_parts empty."""


class MajorQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    major: str = Field(min_length=1, max_length=120, pattern=r"^[^\[\]\r\n|]+$")
    question: str = Field(min_length=1, max_length=2000)
    search_question: str | None = Field(default=None, min_length=1, max_length=2000)


class ExternalPart(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    route: Literal["general", "web", "clarify"]
    question: str = Field(min_length=1, max_length=1000)
    clarification: str | None = Field(default=None, min_length=1, max_length=300)


class QueryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["search", "clarify"]
    standalone_query: str | None = None
    search_query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)] | None = None
    answer_language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    clarification: str | None = None
    scope: Literal["answer", "compare", "inventory"] = "answer"
    major_queries: list[MajorQuery] = Field(default_factory=list, max_length=MAX_MAJOR_QUERIES)
    comparison_criteria: list[ComparisonCriterion] = Field(default_factory=list, max_length=4)
    include_internal: bool = True
    external_parts: list[ExternalPart] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "QueryDecision":
        if self.action == "search":
            if self.include_internal and (self.standalone_query is None or not self.standalone_query.strip()):
                raise ValueError("search requires standalone_query")
            if not self.include_internal and not self.external_parts:
                raise ValueError("search requires at least one question part")
            if len({part.route for part in self.external_parts}) != len(self.external_parts):
                raise ValueError("Each external route can run at most once")
            if any(part.route == "clarify" and not part.clarification for part in self.external_parts):
                raise ValueError("An ambiguous part requires clarification")
            self.standalone_query = self.standalone_query.strip() if self.standalone_query else None
            self.clarification = None
            if self.scope == "inventory" and self.major_queries:
                raise ValueError("Inventory cannot include individual major queries")
            if self.scope == "compare" and len(self.major_queries) < 2:
                raise ValueError("A comparison requires at least two majors")
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
    scope: Literal["answer", "compare", "inventory"] = "answer"
    major_queries: tuple[MajorQuery, ...] = ()
    comparison_criteria: tuple[str, ...] = ()
    include_internal: bool = True
    external_parts: tuple[ExternalPart, ...] = ()
    search_query: str | None = None
    answer_language: str | None = None


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
