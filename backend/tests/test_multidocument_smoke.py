"""Offline checks for sample matching, case selection and smoke artifacts."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from test_extraction import create_two_page_pdf

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_multidocument_smoke as smoke


class SmokeRunnerTests(unittest.TestCase):
    def test_sample_match_requires_pdf_hash_and_reports_name_only_matches(self):
        sample = {"file": "program/sheet.pdf", "sha256": "ab" * 32}
        rows = [
            {"id": "other-type", "filename": "sheet.pdf", "sha256": sample["sha256"], "mime_type": "text/html"},
            {"id": "old", "filename": "sheet.pdf", "sha256": "cd" * 32, "mime_type": "application/pdf"},
            {"id": "legacy", "filename": "Sheet.PDF", "sha256": None, "mime_type": "application/pdf"},
            {"id": "renamed", "filename": "new-name.pdf", "sha256": sample["sha256"], "mime_type": "application/pdf"},
        ]
        for count, expected in enumerate(("missing", "different_version", "version_unverified", "matched"), 1):
            with self.subTest(count=count):
                result = smoke.sample_status(sample, rows[:count])
                self.assertEqual(result["status"], expected)
                self.assertEqual([item["document_id"] for item in result["documents"]],
                                 [row["id"] for row in rows[1:count]])
        self.assertEqual([m["status"] for m in result["documents"]],
                         ["different_version", "version_unverified", "matched"])

    def test_dry_run_reads_only_requested_cases_and_their_pdfs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "used.pdf").write_bytes(create_two_page_pdf("sample quote", "page two"))
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "samples": {"used": "used.pdf", "unused": "not-on-disk.pdf"},
                "cases": [{"id": "first", "evidence": [["used", 1, "sample quote"]]},
                          {"id": "other", "evidence": [["unused", 1, "quote"]]},
                          {"id": "last", "evidence": [["used", 2, "page two"]]}],
            }), encoding="utf-8")
            output = root / "dry.json"
            args = ["smoke", "--dry-run", "--samples-dir", str(root), "--output", str(output),
                    "--case-id", "last", "--case-id", "first"]
            with patch.object(smoke, "SMOKE", manifest), patch.object(sys, "argv", args), patch.object(smoke, "run_live") as live:
                self.assertEqual(smoke.main(), 0)
                live.assert_not_called()
                self.assertEqual([c["id"] for c in smoke.prepare(root, ["last"])["cases"]], ["last"])
                with self.assertRaisesRegex(ValueError, "Unknown smoke case: typo"):
                    smoke.prepare(root, ["typo", "other"])
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["mode"], "dry-run")
            self.assertEqual([c["id"] for c in report["cases"]], ["first", "last"])
            self.assertEqual([c["status"] for c in report["cases"]], ["not_run", "not_run"])
            self.assertEqual(list(report["samples"]), ["used"])

    def test_live_report_keeps_per_case_diagnostics_even_on_answer_error(self):
        # Import the offline DB/config fixture before loading any backend module.
        import test_source_activation
        from langchain_google_genai.chat_models import GoogleAPIError, GoogleRateLimitError
        from rag.progress import current, notify
        from rag.qa import QuestionAnswer

        sensitive = "simulated private prompt, document and secret; message mentions 429"
        failures = (
            (GoogleAPIError(code=503, response_json={"error": {"message": sensitive}}), "query", None, 503),
            (GoogleRateLimitError(sensitive), "generation", "rate_limit", None),
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "samples": {},
                "cases": [{"id": name, "question": name, "evidence": []}
                          for name in ("inventory", "comparison", "three-majors")],
            }), encoding="utf-8")

            for failure, stage, kind, code in failures:
                with self.subTest(stage=stage):
                    session = MagicMock()
                    session.execute.side_effect = [[], []]
                    session_factory = MagicMock()
                    session_factory.return_value.__enter__.return_value = session

                    def answer(db, question, *, diagnostics):
                        self.assertIs(db, session)
                        notify("query")
                        diagnostics.plan["scope"] = question
                        if question == "inventory":
                            notify("retrieval")
                            diagnostics.inventory.append({"document_id": "1", "major": None,
                                                          "recognition": "missing_opening_chunk"})
                            notify("validation")
                            return QuestionAnswer("incomplete", [], cited_source_indices=())
                        self.assertEqual(question, "comparison")
                        notify(stage)
                        raise failure

                    output = root / f"{stage}.json"
                    args = ["smoke", "--live", "--samples-dir", str(root), "--output", str(output)]
                    terminal = StringIO()
                    with (
                        patch.object(test_source_activation.settings, "rag_query_model", "offline", create=True),
                        patch.object(test_source_activation.settings, "rag_generation_model", "offline", create=True),
                        patch("database.SessionLocal", session_factory),
                        patch("rag.qa.answer_question", side_effect=answer) as ask,
                        patch.object(smoke, "SMOKE", manifest),
                        patch.object(sys, "argv", args),
                        redirect_stdout(terminal),
                    ):
                        self.assertEqual(smoke.main(), 1)
                    self.assertEqual([call.args[1] for call in ask.call_args_list], ["inventory", "comparison"])
                    self.assertIn("READ ONLY", str(session.execute.call_args_list[0].args[0]))
                    session.commit.assert_not_called()
                    self.assertIsNone(current.get())
                    self.assertIn("selected=3, completed=1, error=1, not_run=1", terminal.getvalue())
                    artifact = output.read_text(encoding="utf-8")
                    self.assertNotIn(sensitive, terminal.getvalue() + artifact)
                    inventory, failed, skipped = json.loads(artifact)["cases"]
                    self.assertEqual(inventory["status"], "completed")
                    self.assertEqual(inventory["diagnostics"]["inventory"][0]["recognition"], "missing_opening_chunk")
                    self.assertEqual(failed["status"], "error")
                    self.assertEqual(failed["diagnostics"]["plan"], {"scope": "comparison"})
                    self.assertEqual(failed["error_type"], type(failure).__name__)
                    self.assertEqual(failed["error_stage"], stage)
                    self.assertEqual(failed["provider_error_kind"], kind)
                    self.assertEqual(failed["provider_status_code"], code)
                    self.assertEqual(skipped, {"id": "three-majors", "question": "three-majors",
                                               "evidence": [], "status": "not_run"})
