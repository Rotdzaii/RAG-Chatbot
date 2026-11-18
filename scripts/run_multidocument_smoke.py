"""Manual evidence review on the active corpus. Dry-run only reads local sample PDFs."""

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from threading import Event
from uuid import uuid4

from pypdf import PdfReader

from rag_baseline import write_run_output

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "evals" / "smoke" / "multidocument.json"


def prepare(samples_dir: Path, case_ids: list[str] | None = None) -> dict:
    rubric = json.loads(SMOKE.read_text(encoding="utf-8"))
    cases = rubric["cases"]
    if case_ids:
        unknown = set(case_ids) - {case["id"] for case in cases}
        if unknown:
            raise ValueError("Unknown smoke case: " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case["id"] in case_ids]
    needed = {name for case in cases for name, _, _ in case["evidence"]}
    pages = {}
    samples = {}
    for name, relative in rubric["samples"].items():
        if name not in needed:
            continue
        path = samples_dir / relative
        reader = PdfReader(path)
        pages[name] = [" ".join(page.extract_text().split()) for page in reader.pages]
        samples[name] = {"file": relative, "sha256": sha256(path.read_bytes()).hexdigest()}
    for case in cases:
        for name, page, quote in case["evidence"]:
            if not 1 <= page <= len(pages[name]) or quote not in pages[name][page - 1]:
                raise ValueError(f"{case['id']}: sample quote mismatch ({name}, page {page})")
    return {"samples": samples, "cases": [{**case, "status": "not_run"} for case in cases]}


def sample_status(sample: dict, active_documents: list[dict]) -> dict:
    basename = Path(sample["file"]).name.casefold()
    matches = []
    for doc in active_documents:
        if doc["mime_type"] != "application/pdf":
            continue
        digest = (doc["sha256"] or "").lower()
        if digest == sample["sha256"]:
            status = "matched"
        elif doc["filename"].casefold() == basename:
            status = "different_version" if digest else "version_unverified"
        else:
            continue
        matches.append({"document_id": doc["id"], "filename": doc["filename"], "status": status})
    statuses = {match["status"] for match in matches}
    status = next((value for value in ("matched", "version_unverified", "different_version")
                   if value in statuses), "missing")
    return {"status": status, "documents": matches}


def run_live(report: dict) -> bool:
    sys.path.insert(0, str(ROOT / "backend"))
    from sqlalchemy import select, text
    from config import settings
    from database import SessionLocal
    from rag.models import Document
    from rag.progress import ProgressContext, Stage, current
    from rag.provider_errors import provider_error_kind, provider_status_code
    from rag.qa import answer_question
    from rag.qa_diagnostics import QuestionDiagnostics

    stage: Stage | None = None

    def record_stage(value: Stage) -> None:
        nonlocal stage
        stage = value

    report["models"] = {"query": settings.rag_query_model, "generation": settings.rag_generation_model}
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        statement = select(Document.id, Document.filename, Document.content_hash, Document.mime_type).where(
            Document.is_active.is_(True)).order_by(Document.id)
        report["active_documents"] = [
            {"id": str(row.id), "filename": row.filename, "sha256": row.content_hash, "mime_type": row.mime_type}
            for row in session.execute(statement)
        ]
        for sample in report["samples"].values():
            sample["active_corpus"] = sample_status(sample, report["active_documents"])
            print(f"{sample['file']}: {sample['active_corpus']['status']}")
        for case in report["cases"]:
            trace = QuestionDiagnostics()
            stage = None
            token = current.set(ProgressContext(uuid4(), "", Event(), record_stage))
            try:
                result = answer_question(session, case["question"], diagnostics=trace)
            except Exception as exc:
                case.update(
                    status="error",
                    error_stage=stage,
                    error_type=type(exc).__name__,
                    provider_error_kind=provider_error_kind(exc),
                    provider_status_code=provider_status_code(exc),
                )
                return False
            finally:
                current.reset(token)
                case["diagnostics"] = asdict(trace)
            case["answer"] = result.answer
            case["rewritten_query"] = result.rewritten_query
            case["cited_indices"] = result.cited_source_indices
            case["context"] = [
                {**asdict(source), "citation": i, "chunk_id": str(source.chunk_id),
                 "document_id": str(source.document_id),
                 "source_file_version_id": str(source.source_file_version_id) if source.source_file_version_id else None}
                for i, source in enumerate(result.sources, 1)
            ]
            case["status"] = "completed"
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", action="append", help="Only run this case ID. Repeat to select multiple cases.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists. Choose a new artifact path.")
    try:
        report = prepare(args.samples_dir, args.case_id)
    except ValueError as exc:
        parser.error(str(exc))
    report["mode"] = "live" if args.live else "dry-run"
    succeeded = run_live(report) if args.live else True
    write_run_output(report, args.output)
    cases = report["cases"]
    completed = sum(case["status"] == "completed" for case in cases)
    errors = sum(case["status"] == "error" for case in cases)
    print(f"{report['mode']}: selected={len(cases)}, completed={completed}, "
          f"error={errors}, not_run={len(cases) - completed - errors}. Artifact: {args.output}")
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
