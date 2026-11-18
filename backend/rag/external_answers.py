"""Gemini answers for public requests and verified Google Search citations."""

import re
from typing import Literal
from urllib.parse import urlsplit

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from rag.citations import cited_source_indices
from rag.langchain_pipeline import MODEL
from rag.progress import notify
from rag.question_outcomes import Outcome, Resolution, mark_executed


GENERAL_UNAVAILABLE = "Hiện chưa thể trả lời phần kiến thức chung. Bạn có thể thử lại sau."
WEB_UNAVAILABLE = "Hiện chưa thể xác minh thông tin cập nhật từ web. Bạn có thể thử lại sau."
_LINK = re.compile(r"https?://|www\.|\]\s*\(|<[^>]*>|[^\s@]+@[^\s@]+\.[^\s@]+", re.I)


class WebSource(BaseModel):
    title: str
    url: str


class GroundedResult(BaseModel):
    text: str
    sources: list[WebSource]
    search_suggestions_html: str


class GeneralAnswer(BaseModel):
    outcome: Literal["answered", "partial", "clarification", "unavailable"]
    answer: str


class CredentialsUnavailable(RuntimeError):
    pass


def _generate(question: str, *, use_search: bool) -> types.GenerateContentResponse:
    from config import settings

    key = settings.gemini_api_key
    if key is None or not key.get_secret_value():
        raise CredentialsUnavailable("Gemini credentials unavailable")
    instruction = (
        "Answer in the question's language. Give a short plain-text answer grounded entirely "
        "in Google Search. Support every factual claim. Do not write links, citations, "
        "source lists or Markdown in the text."
        if use_search else
        "Answer in the question's language using general knowledge. Do not claim to know "
        "VLU policy or internal documents. Do not give current information or add source references. "
        "Report whether all, some, or none of the requested items were answered. Use clarification "
        "when more user input is needed."
    )
    config = types.GenerateContentConfig(
        system_instruction=instruction,
        tools=[types.Tool(google_search=types.GoogleSearch())] if use_search else None,
        response_mime_type=None if use_search else "application/json",
        response_schema=None if use_search else GeneralAnswer,
        max_output_tokens=1024,
    )
    http_options = types.HttpOptions(timeout=12_000, retry_options=types.HttpRetryOptions(attempts=1))
    with genai.Client(api_key=key.get_secret_value(), vertexai=False, http_options=http_options) as client:
        mark_executed("web" if use_search else "general")
        return client.models.generate_content(
            model=getattr(settings, "rag_generation_model", MODEL),
            contents=question,
            config=config,
        )


def general_answer(question: str) -> tuple[str, Resolution]:
    notify("generation")
    try:
        result = GeneralAnswer.model_validate_json(_generate(question, use_search=False).text or "")
        if result.outcome == "unavailable":
            return GENERAL_UNAVAILABLE, Resolution(Outcome.UNAVAILABLE, ("general_unavailable",))
        answer = result.answer.strip()
        if not answer:
            raise ValueError("Empty general answer")
        cited_source_indices(answer, 0)
        reason = {"partial": ("unanswered_items",), "clarification": ("missing_input",)}
        return answer, Resolution(Outcome(result.outcome), reason.get(result.outcome, ()))
    except CredentialsUnavailable:
        return GENERAL_UNAVAILABLE, Resolution(Outcome.UNAVAILABLE, ("credentials_unavailable",))
    except (errors.APIError, httpx.HTTPError, TimeoutError, RuntimeError):
        return GENERAL_UNAVAILABLE, Resolution(Outcome.ERROR, ("provider_error",))
    except ValueError:
        return GENERAL_UNAVAILABLE, Resolution(Outcome.ERROR, ("invalid_generation",))


def _host(url: str) -> str | None:
    if re.search(r"[\s\\\x00-\x1f\x7f]", url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme in {"https", "http"} and parsed.username is None:
            return parsed.hostname
    except ValueError:
        pass
    return None


def _parse_grounded(response: types.GenerateContentResponse) -> GroundedResult | None:
    if not response.candidates:
        return None
    candidate = response.candidates[0]
    metadata = candidate.grounding_metadata
    if not metadata or not metadata.web_search_queries or not candidate.content:
        return None
    if candidate.finish_reason not in (None, types.FinishReason.STOP):
        return None
    entry_point = metadata.search_entry_point
    suggestions = entry_point.rendered_content if entry_point else None
    if not suggestions or not suggestions.strip():
        return None

    # Offsets use UTF-8 bytes within the original part, including any preceding
    # thought parts in the part numbering. Never render or store those thoughts.
    supports = metadata.grounding_supports or []
    chunks = metadata.grounding_chunks or []
    sources: dict[str, WebSource] = {}
    text_parts = []
    for part_index, part in enumerate(candidate.content.parts or []):
        if not part.text or part.thought:
            continue
        if _LINK.search(part.text) or re.search(r"\[\d", part.text):
            return None
        raw = part.text.encode("utf-8")
        spans: list[tuple[int, int, list[tuple[str, str]]]] = []
        for support in supports:
            segment = support.segment
            if not segment or (segment.part_index or 0) != part_index:
                continue
            start, end = segment.start_index or 0, segment.end_index
            if end is None or not 0 <= start < end <= len(raw):
                continue
            try:
                snippet = raw[start:end].decode("utf-8")
            except UnicodeDecodeError:
                continue
            if not snippet.strip() or (segment.text and snippet != segment.text):
                continue
            links = []
            for index in support.grounding_chunk_indices or []:
                web = chunks[index].web if 0 <= index < len(chunks) else None
                if web and web.uri and (host := _host(web.uri)):
                    links.append((web.uri, web.title or host))
            if links:
                spans.append((start, end, links))

        covered_until = 0
        for start, end, links in sorted(spans):
            if start > covered_until and any(char.isalnum() for char in raw[covered_until:start].decode("utf-8")):
                return None
            covered_until = max(covered_until, end)
            for url, title in links:
                if url not in sources:
                    sources[url] = WebSource(title=title, url=url)
        if any(char.isalnum() for char in raw[covered_until:].decode("utf-8")):
            return None
        text_parts.append(part.text)
    if not sources:
        return None
    return GroundedResult(text="".join(text_parts), sources=list(sources.values()), search_suggestions_html=suggestions)


def web_answer(question: str) -> tuple[GroundedResult | None, Resolution]:
    from config import settings

    if not getattr(settings, "rag_google_search_enabled", False):
        return None, Resolution(Outcome.UNAVAILABLE, ("search_disabled",))
    notify("web_search")
    try:
        result = _parse_grounded(_generate(question, use_search=True))
        if result is None:
            return None, Resolution(Outcome.INSUFFICIENT, ("missing_grounding",))
        return result, Resolution(Outcome.ANSWERED)
    except CredentialsUnavailable:
        return None, Resolution(Outcome.UNAVAILABLE, ("credentials_unavailable",))
    except (errors.APIError, httpx.HTTPError, TimeoutError, RuntimeError):
        return None, Resolution(Outcome.ERROR, ("provider_error",))
    except ValueError:
        return None, Resolution(Outcome.ERROR, ("invalid_generation",))
