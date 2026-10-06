import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from rag_retrieval_probe import build_report, select_direct_cases


def case(case_id, query_type="standalone", status="approved", retrieval="applicable", history=None):
    return {
        "id": case_id, "question": "Question?", "query_type": query_type,
        "review_status": status, "history": history or [],
        "metric_applicability": {"retrieval": retrieval},
        "evidence": [{"kind": "supporting", "chunk_id": "gold"}],
    }


class RetrievalProbeTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"cases": [case("direct"), case("follow", "follow_up"),
                                   case("pending", status="pending_review"),
                                   case("ambig", "ambiguous", retrieval="not_applicable")]}
        self.snapshot = {"fingerprint": "matching-snapshot"}

    def test_selects_only_approved_independent_retrieval_cases(self):
        selected, excluded = select_direct_cases(self.manifest)
        self.assertEqual([item["id"] for item in selected], ["direct"])
        self.assertEqual(len(excluded), 3)
        with self.assertRaisesRegex(ValueError, "Unknown case ID"):
            select_direct_cases(self.manifest, "missing")

    def test_sweeps_offline_from_one_fetch_per_question(self):
        calls = []
        candidates = [
            SimpleNamespace(chunk_id="other", document_id="doc", filename="a.pdf",
                            chunk_index=0, page_start=1, page_end=1, cosine_distance=0.19),
            SimpleNamespace(chunk_id="gold", document_id="doc", filename="a.pdf",
                            chunk_index=1, page_start=2, page_end=2, cosine_distance=0.32),
        ]
        def fetch(question):
            calls.append(question)
            return candidates

        report = build_report(self.manifest, self.snapshot, fetch=fetch)
        self.assertEqual(calls, ["Question?"])
        self.assertEqual(report["run_status"], "complete")
        self.assertEqual(len(report["scenario_aggregates"]), 15)
        row = report["cases"][0]
        self.assertNotIn("content", row["candidates"][0])
        self.assertFalse(row["scenarios"][8]["retrieval_metrics"]["evidence_hit"])
        self.assertTrue(row["scenarios"][9]["retrieval_metrics"]["evidence_hit"])

    def test_dry_run_does_not_fetch_and_does_not_score(self):
        report = build_report(self.manifest, self.snapshot)
        self.assertEqual(report["run_status"], "dry_run")
        self.assertEqual(report["scenario_aggregates"], [])

    def test_error_stops_remaining_cases_without_leaking_exception(self):
        self.manifest["cases"].append(case("another"))
        calls = []
        def failing(question):
            calls.append(question)
            raise RuntimeError("secret key and private URL")
        report = build_report(self.manifest, self.snapshot, fetch=failing)
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["run_status"], "incomplete")
        self.assertEqual(report["scenario_aggregates"], [])
        self.assertEqual(report["cases"][1]["status"], "not_run")
        self.assertNotIn("secret", str(report))


if __name__ == "__main__":
    unittest.main()
