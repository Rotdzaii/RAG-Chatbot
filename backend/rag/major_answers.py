from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations, zip_longest
import re

from langchain_core.documents import Document
from langchain_core.runnables.config import RunnableConfig
from sqlalchemy.orm import Session

from rag.citations import cited_source_indices
from rag.langchain_pipeline import format_documents, grounded_answer_chain, grounded_comparison_chain
from rag.langchain_retriever import SQLAlchemyVectorRetriever
from rag.major_catalog import MajorCatalog, major_key
from rag.qa_diagnostics import QuestionDiagnostics, observe_search
from rag.query_contract import MajorQuery
from rag.question_outcomes import Outcome, Resolution, combine_resolutions
from rag.source_metadata import RetrievalFilters


_MISSING = "Chưa đủ thông tin trong các tài liệu đang sử dụng."
_BUDGET = "Chưa đủ ngân sách đoạn trích để trả lời tiêu chí này."
MAX_CHUNK_CHARACTERS = 1000  # Also bounds evidence from legacy or externally indexed chunks.
MIN_CANDIDATES_PER_SEARCH = 10

_CODE_CRITERION = re.compile(r"^mã(?: số)? ngành\b")
_MAJOR_CODE = re.compile(r"\bmã(?: số)? ngành\s*[:：]?\s*[0-9]{7}\b")
_INTAKE_YEAR = re.compile(r"\b(?:nhập học|tuyển sinh)(?:\s+năm)?\s*[:：]?\s*(20[0-9]{2})\b")


def _search_query(name: str, question: str, criterion: str | None) -> str:
    scope = major_key(question)
    subject = rf"(?<!\w){re.escape(major_key(name))}(?!\w)"
    # The resolver can insert "của ngành X" in the middle of a criterion.
    criterion_scope = " ".join(re.sub(rf"\bcủa (?:ngành )?{subject}", "", scope).split())
    missing = []
    if criterion and not re.search(rf"(?<!\w){re.escape(major_key(criterion))}(?!\w)", criterion_scope):
        missing.append(criterion)
    if not re.search(subject, scope):
        missing.append(name)
    return " — ".join([*missing, question])


def _eligible_passages(hits: list[Document], criterion: str | None, question: str) -> list[Document]:
    # Program codes have a verifiable field and format. Keep semantic retrieval for
    # open-ended criteria that cannot be validated from a field.
    if criterion is None or not _CODE_CRITERION.match(major_key(criterion)):
        return hits
    scope = major_key(f"{criterion} {question}")
    intake_years = set(_INTAKE_YEAR.findall(scope))
    # Enforce an intake year only when the question points to a single year.
    # The answer prompt retains all date conditions for more complex requests.
    require_year = len(intake_years) == 1 and intake_years == set(re.findall(r"\b20[0-9]{2}\b", scope))
    eligible = []
    for hit in hits:
        content = major_key(hit.page_content[:MAX_CHUNK_CHARACTERS])
        for code in _MAJOR_CODE.finditer(content):
            # A matching year elsewhere in the chunk could belong to another field.
            nearby = content[max(0, code.start() - 120):code.end() + 120]
            if not require_year or set(_INTAKE_YEAR.findall(nearby)) == intake_years:
                eligible.append(hit)
                break
    return eligible


def _checked_cell(answer: str, resolution: Resolution, allowed: set[int], last: int) -> tuple[str, Resolution]:
    if resolution.outcome == Outcome.INSUFFICIENT:
        return _MISSING, resolution
    cited = cited_source_indices(answer, last)
    if not allowed.issuperset(cited):
        raise ValueError("Generated answer references a citation outside its major or criterion")
    if not cited:
        return _MISSING, Resolution(Outcome.ERROR, ("unverified_answer",))
    return answer.strip(), resolution


def _table_row(cells: Iterable[str]) -> str:
    return "| " + " | ".join(" ".join(cell.split()).replace("|", r"\|") for cell in cells) + " |"


@dataclass
class _Evidence:
    documents: list[Document]
    # For each criterion, the global citation numbers surviving its own search.
    allowed: list[set[int]]
    missing: list[tuple[str, Resolution]]


def _select_evidence(ranked: list[list[Document]], quota: int, first: int) -> _Evidence:
    candidates = [{doc.metadata["chunk_id"]: doc for doc in hits} for hits in ranked]
    passages: dict[str, Document] = {}
    for hits in candidates:
        for key, doc in hits.items():
            if key not in passages or doc.metadata["cosine_distance"] < passages[key].metadata["cosine_distance"]:
                passages[key] = doc
    leaders = dict.fromkeys(next(iter(hits)) for hits in candidates if hits)
    selected = {key: passages[key] for key in leaders}
    if len(leaders) > quota:
        # At most four criteria. This branch has quota <= 3 and at most
        # four times MIN_CANDIDATES_PER_SEARCH candidates.
        # Cover as many criteria as possible, then prefer the best per-query ranks.
        ranks = [{key: rank for rank, key in enumerate(hits)} for hits in candidates]

        def quality(keys: tuple[str, ...]) -> tuple[int, int]:
            best = [min((rank[key] for key in keys if key in rank), default=None) for rank in ranks]
            return best.count(None), sum(value for value in best if value is not None)

        keys = min(combinations(passages, quota), key=quality)
        selected = {key: passages[key] for key in keys}
    for row in zip_longest(*candidates):
        if len(selected) >= quota:
            break
        for key in row:
            if key is not None and len(selected) < quota:
                selected.setdefault(key, passages[key])
    numbers = {key: number for number, key in enumerate(selected, first)}
    allowed = [{numbers[key] for key in hits if key in numbers} for hits in candidates]
    missing = [
        (_BUDGET, Resolution(Outcome.INSUFFICIENT, ("context_budget",))) if hits and not refs
        else (_MISSING, Resolution(Outcome.INSUFFICIENT, ("missing_evidence",)))
        for hits, refs in zip(candidates, allowed)
    ]
    return _Evidence(list(selected.values()), allowed, missing)


def answer_by_major(
    session: Session, catalog: MajorCatalog, parts: tuple[MajorQuery, ...],
    *, criteria: tuple[str, ...], top_k: int, filters: RetrievalFilters | None,
    config: RunnableConfig | None,
    diagnostics: QuestionDiagnostics | None = None,
) -> tuple[str, list[Document], Resolution]:
    # Reserve each subject's share before searching. Finish all reads before
    # generation so progress stages stay ordered and the same Session is used serially.
    groups = []
    documents: list[Document] = []
    quota, extra = divmod(top_k, len(parts))
    for index, part in enumerate(parts):
        entry = catalog.majors.get(major_key(part.major))
        budget = quota + int(index < extra)
        candidate_limit = max(MIN_CANDIDATES_PER_SEARCH, budget)
        name = entry.name if entry else part.major
        retriever = None
        if entry:
            retriever = SQLAlchemyVectorRetriever(
                session=session, filters=filters, top_k=candidate_limit,
                subject_headers=tuple(entry.header_ids),
            )
        ranked = []
        observations = []
        for criterion in criteria or (None,):
            query = _search_query(name, part.question, criterion)
            with observe_search(diagnostics, name, criterion, part.question, query,
                                candidate_limit=candidate_limit, context_budget=budget) as observation:
                hits = retriever.invoke(query, config=config) if retriever is not None else []
                eligible = _eligible_passages(hits, criterion, part.question)
                ranked.append(eligible)
                if observation is not None:
                    if retriever is None:
                        observation.status = "no_identified_document"
                    observations.append(observation)
        evidence = _select_evidence(ranked, budget, len(documents) + 1)
        if observations:
            numbers = {doc.metadata["chunk_id"]: number for number, doc in
                       enumerate(evidence.documents, len(documents) + 1)}
            for observation, eligible in zip(observations, ranked):
                observation.record_selection(numbers, {doc.metadata["chunk_id"] for doc in eligible})
        groups.append((name, part.question, evidence))
        documents.extend(evidence.documents)

    sections: list[str] = []
    columns: list[list[str]] = []
    outcomes = []
    generation = None
    first = 1
    for name, subquestion, evidence in groups:
        cells = evidence.missing.copy()
        if evidence.documents:
            if generation is None:
                generation = grounded_comparison_chain() if criteria else grounded_answer_chain()
            prompt = {
                "question": (
                    f"Chỉ xét ngành {name}. {subquestion}\n"
                    "Chỉ trích dẫn đoạn xác nhận thông tin cho chính ngành đang xét. "
                    "Nếu đoạn chỉ nêu ví dụ về ngành khác hoặc thiếu dữ kiện, "
                    "hãy báo chưa đủ thông tin và để phần đó không có trích dẫn."
                ),
                "context": format_documents(evidence.documents, first, character_limit=MAX_CHUNK_CHARACTERS),
            }
            covered = [i for i, refs in enumerate(evidence.allowed) if refs]
            if criteria:
                prompt["question"] += "\nTrả lời từng tiêu chí theo đúng thứ tự, chỉ dùng các đoạn tương ứng:\n"
                for i in covered:
                    refs = ", ".join(str(ref) for ref in sorted(evidence.allowed[i]))
                    prompt["question"] += f"{criteria[i]} (đoạn {refs})\n"
                replies = generation.invoke(prompt, config=config).cells
                if len(replies) != len(covered):
                    raise ValueError("Comparison response does not match requested criteria")
            else:
                replies = [generation.invoke(prompt, config=config)]
            for i, reply in zip(covered, replies):
                cells[i] = _checked_cell(reply.answer, reply.resolution, evidence.allowed[i], len(documents))
            first += len(evidence.documents)
        texts, resolutions = zip(*cells)
        outcomes.extend(resolutions)
        if criteria:
            columns.append(list(texts))
        else:
            sections.append(f"**{name}**\n\n{texts[0]}")

    if criteria:
        rows = [_table_row(["Tiêu chí", *(name for name, _, _ in groups)]),
                _table_row(["---"] * (1 + len(groups)))]
        for index, criterion in enumerate(criteria):
            rows.append(_table_row([criterion, *(column[index] for column in columns)]))
        return "\n".join(rows), documents, combine_resolutions(outcomes)
    return "\n\n".join(sections), documents, combine_resolutions(outcomes)
