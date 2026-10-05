from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from langchain_google_genai.chat_models import GoogleRateLimitError


fake_config = ModuleType("config")
fake_config.settings = SimpleNamespace(
    database_url="postgresql+psycopg://user:password@localhost/test"
)
sys.modules.setdefault("config", fake_config)

from rag.query_processing import (  # noqa: E402
    HistoryMessage,
    QueryDecision,
    QueryProcessingError,
    process_query,
)


def query_model_returning(payload: object) -> tuple[Mock, Mock]:
    model = Mock()
    structured_model = Mock()
    structured_model.invoke.return_value = payload
    model.with_structured_output.return_value = structured_model
    return model, structured_model


class QueryProcessingTests(unittest.TestCase):
    def test_follow_up_is_resolved_from_supplied_history(self) -> None:
        history = [
            HistoryMessage(
                role="user",
                content="Ngành Marketing có những chuyên ngành nào?",
            ),
            HistoryMessage(
                role="assistant",
                content="Ngành Marketing có bốn chuyên ngành.",
            ),
        ]
        model, structured = query_model_returning(
            QueryDecision(
                action="search",
                standalone_query="Ngành Marketing học trong bao lâu?",
            )
        )

        with (
            patch("rag.query_processing._get_query_model", return_value=model),
            patch(
                "rag.query_processing.time.perf_counter",
                side_effect=[10.0, 10.012],
            ),
        ):
            result = process_query("Ngành đó học bao lâu?", history)

        self.assertEqual(result.action, "search")
        self.assertEqual(
            result.standalone_query,
            "Ngành Marketing học trong bao lâu?",
        )
        self.assertTrue(result.history_used)
        self.assertAlmostEqual(result.elapsed_ms, 12.0)
        model.with_structured_output.assert_called_once_with(QueryDecision)

        rendered = "\n".join(
            str(message.content)
            for message in structured.invoke.call_args.args[0].to_messages()
        )
        self.assertIn("Ngành Marketing có những chuyên ngành nào?", rendered)
        self.assertIn("Ngành đó học bao lâu?", rendered)

    def test_ambiguous_question_without_history_returns_clarification(self) -> None:
        model, _ = query_model_returning(
            {
                "action": "clarify",
                "standalone_query": None,
                "clarification": "Bạn đang muốn hỏi về ngành nào?",
            }
        )

        with patch("rag.query_processing._get_query_model", return_value=model):
            result = process_query("Ngành này có những chuyên ngành nào?")

        self.assertEqual(result.action, "clarify")
        self.assertEqual(result.clarification, "Bạn đang muốn hỏi về ngành nào?")
        self.assertIsNone(result.standalone_query)
        self.assertFalse(result.history_used)

    def test_prompt_prioritizes_current_question_when_topic_changes(self) -> None:
        history = [
            HistoryMessage(role="user", content="Marketing học bao lâu?"),
            HistoryMessage(role="assistant", content="3,5 năm."),
        ]
        model, structured = query_model_returning(
            QueryDecision(
                action="search",
                standalone_query="Ngành Kỹ thuật phần mềm học những môn nào?",
            )
        )

        with patch("rag.query_processing._get_query_model", return_value=model):
            result = process_query(
                "Còn ngành Kỹ thuật phần mềm học những môn nào?",
                history,
            )

        self.assertEqual(
            result.standalone_query,
            "Ngành Kỹ thuật phần mềm học những môn nào?",
        )
        rendered = "\n".join(
            str(message.content)
            for message in structured.invoke.call_args.args[0].to_messages()
        )
        self.assertIn("current question has priority", rendered)
        self.assertIn("Never force a new", rendered)

    def test_provider_failure_is_distinct_and_logs_no_content(self) -> None:
        model, structured = query_model_returning({})
        provider_error = GoogleRateLimitError(
            "private provider detail https://provider.invalid secret-key"
        )
        structured.invoke.side_effect = provider_error
        question = "sensitive current question"
        history = [HistoryMessage(role="user", content="sensitive history")]

        with (
            patch("rag.query_processing._get_query_model", return_value=model),
            patch(
                "rag.query_processing.time.perf_counter",
                side_effect=[20.0, 20.025],
            ),
            self.assertLogs("uvicorn.error", level="INFO") as captured,
        ):
            with self.assertRaises(QueryProcessingError) as captured_error:
                process_query(question, history)

        error = captured_error.exception
        self.assertIs(error.__cause__, provider_error)
        self.assertEqual(error.error_stage, "query_processing")
        self.assertEqual(error.cause_type, "GoogleRateLimitError")
        self.assertEqual(error.category, "provider")
        self.assertEqual(error.provider_error_kind, "rate_limit")
        self.assertIsNone(error.provider_status_code)
        self.assertAlmostEqual(error.elapsed_ms or 0, 25.0)
        self.assertEqual(str(error), "Query processing failed")
        logs = "\n".join(captured.output)
        self.assertIn("query processing error", logs)
        self.assertIn("history_used=True", logs)
        self.assertNotIn(question, logs)
        self.assertNotIn("sensitive history", logs)
        self.assertNotIn("private provider detail", logs)
        self.assertNotIn("provider.invalid", logs)
        self.assertNotIn("secret-key", logs)

    def test_invalid_structured_payload_is_rejected(self) -> None:
        model, _ = query_model_returning(
            {"action": "search", "standalone_query": "  "}
        )

        with patch("rag.query_processing._get_query_model", return_value=model):
            with self.assertRaises(QueryProcessingError) as captured:
                process_query("Câu hỏi")

        self.assertEqual(captured.exception.category, "schema_validation")
        self.assertEqual(captured.exception.cause_type, "ValidationError")
        self.assertIsNone(captured.exception.provider_status_code)

    def test_prompt_requires_preserving_standalone_query_constraints(self) -> None:
        question = (
            "Theo phần giải đáp của tài liệu, trong năm 2026 sinh viên học "
            "những lĩnh vực nào?"
        )
        model, structured = query_model_returning(
            QueryDecision(action="search", standalone_query=question)
        )

        with patch("rag.query_processing._get_query_model", return_value=model):
            result = process_query(question)

        self.assertEqual(result.standalone_query, question)
        rendered = "\n".join(
            str(message.content)
            for message in structured.invoke.call_args.args[0].to_messages()
        )
        self.assertIn("already clear and standalone, preserve it unchanged", rendered)
        self.assertIn("named source or document section", rendered)
        self.assertIn("time period", rendered)
        self.assertIn("requested scope", rendered)
        self.assertIn(question, rendered)


if __name__ == "__main__":
    unittest.main()
