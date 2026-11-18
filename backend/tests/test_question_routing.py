"""Question routing through HTTP/SSE with SQLite and mocked Gemini SDK calls."""

import json
import unittest
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from google.genai import errors, types
from langchain_core.runnables import RunnableLambda
from pydantic import SecretStr
from sqlalchemy import select

import test_source_activation as fixture
from rag.external_answers import GENERAL_UNAVAILABLE, WEB_UNAVAILABLE
from rag.conversations import GROUNDING_EXPIRED
from rag.models import Chunk, Document, Message
from rag.query_processing import process_query


PUBLIC = "thời tiết hôm nay ở TP.HCM"
WEB_URL = "https://grounding.example.test/weather?z=2&a=1"
WEB_TEXT = "TP.HCM có mưa rào cục bộ."
SUGGESTIONS = '<a href="https://www.google.com/search?q=thoi+tiet" target="_blank">Thời tiết</a>'


def reply(text):
    return types.GenerateContentResponse(candidates=[
        types.Candidate(content=types.Content(parts=[types.Part(text=text)]))
    ])


def grounded(text=WEB_TEXT, supported=WEB_TEXT, url=WEB_URL, suggestions=SUGGESTIONS):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(parts=[
            types.Part(thought=True, text="private thought"),
            types.Part(text=text),
        ]),
        finish_reason=types.FinishReason.STOP,
        grounding_metadata=types.GroundingMetadata(
            grounding_chunks=[types.GroundingChunk(web=types.GroundingChunkWeb(uri=url, title="Bản tin thời tiết"))],
            grounding_supports=[types.GroundingSupport(
                segment=types.Segment(part_index=1, start_index=0, end_index=len(supported.encode()), text=supported),
                grounding_chunk_indices=[0],
            )],
            web_search_queries=["provider-derived search query"],
            search_entry_point=types.SearchEntryPoint(rendered_content=suggestions) if suggestions else None,
        ),
    )])


class QuestionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.db = fixture.SourceActivationTests()
        self.db.setUp()
        self.addCleanup(self.db.doCleanups)
        self.query_model = Mock()
        self.plan = self.query_model.with_structured_output.return_value.invoke
        self.sdk = Mock()
        self.sdk_context = Mock()
        self.sdk_context.models.generate_content = self.sdk
        for target, value in (
            ("rag.qa.process_query", process_query),
            ("rag.query_processing._get_query_model", Mock(return_value=self.query_model)),
        ):
            p = patch(target, new=value)
            p.start()
            self.addCleanup(p.stop)
        p = patch("rag.external_answers.genai.Client")
        self.client_factory = p.start()
        self.client_factory.return_value.__enter__.return_value = self.sdk_context
        self.addCleanup(p.stop)
        for name, value in (
            ("gemini_api_key", SecretStr("offline")),
            ("rag_generation_model", "gemini-3.6-flash"),
            ("rag_google_search_enabled", True),
        ):
            p = patch.object(fixture.settings, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)

    def choose(self, *, internal=None, routes=(), majors=()):
        self.plan.return_value = {
            "action": "search",
            "standalone_query": internal,
            "include_internal": internal is not None,
            "major_queries": [{"major": major, "question": internal} for major in majors],
            "external_parts": [{"route": route, "question": question} for route, question in routes],
        }

    def seed(self, text):
        with self.db.sessions() as session:
            session.add(Document(
                filename="guide.txt", mime_type="text/plain", is_active=True,
                chunks=[Chunk(chunk_index=0, content=text, embedding=[1.] + [0.] * 767)],
            ))
            session.commit()

    def ask(self, question, **params):
        response = self.db.client.post("/questions", json={"question": question, **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def stream(self, payload):
        response = self.db.client.post("/questions/stream", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]

    def test_internal_missing_stays_internal_even_with_freshness_request(self):
        question = "Quy định nghỉ học mới nhất của VLU?"
        self.choose(internal=question)
        result = self.ask(question)
        self.assertIn("Không có ngữ cảnh", result["answer"])
        self.assertEqual(result["sources"], [])
        self.sdk.assert_not_called()

        self.seed("Quy chế nghỉ học VLU.")
        self.db.model.return_value = RunnableLambda(lambda _: "Một suy đoán không có trích dẫn.")
        result = self.ask(question)
        self.assertIn("Không có ngữ cảnh", result["answer"])
        self.assertNotIn("suy đoán", result["answer"])

    def test_internal_then_general_then_different_internal_major(self):
        self.seed("Ngành: Kiến trúc\nHọc phần: Đồ án")
        self.seed("Ngành: Ngôn ngữ Nhật\nHọc phần: Ngữ âm")
        self.db.model.return_value = RunnableLambda(
            lambda prompt: "Ngữ âm [1]" if "Ngữ âm" in prompt.to_string() else "Đồ án [1]"
        )
        self.choose(internal="Kiến trúc học gì?", majors=("Kiến trúc",))
        first = self.ask("Kiến trúc học gì?")
        self.assertIn("Đồ án [1]", first["answer"])
        self.assertIn("document_id", first["sources"][0])
        self.sdk.assert_not_called()

        question = "Vì sao bầu trời có màu xanh?"
        self.choose(routes=[("general", question)])
        self.sdk.return_value = reply("Do ánh sáng bị tán xạ trong khí quyển.")
        general = self.ask(question, conversation_id=first["conversation_id"])
        self.assertIn("Kiến thức chung", general["answer"])
        self.assertEqual(general["sources"], [])
        request = self.sdk.call_args.kwargs
        self.assertEqual(request["contents"], question)
        self.assertIsNone(request["config"].tools)

        self.choose(internal="Ngôn ngữ Nhật học gì?", majors=("Ngôn ngữ Nhật",))
        last = self.ask("Còn ngành Ngôn ngữ Nhật?", conversation_id=first["conversation_id"])
        self.assertIn("Ngữ âm [1]", last["answer"])
        self.assertNotEqual(last["sources"][0]["document_id"], first["sources"][0]["document_id"])
        self.sdk.assert_called_once()

    def test_mixed_stream_displays_original_text_and_expires_grounding_on_save(self):
        self.seed("Quy định VLU: xin phép nghỉ học trước buổi học.")
        internal = "Quy định nghỉ học VLU"
        self.choose(internal=internal, routes=[("web", PUBLIC)])
        self.db.model.return_value = RunnableLambda(lambda _: "Cần xin phép trước buổi học [1].")
        original = f"  {WEB_TEXT}\n"
        self.sdk.return_value = grounded(text=original, supported=original)
        payload = {"question": f"{internal} và {PUBLIC}", "request_id": str(uuid4())}
        frames = self.stream(payload)
        self.assertEqual([f["stage"] for f in frames if "stage" in f],
                         ["query", "retrieval", "generation", "web_search", "validation"])
        result = frames[-1]["response"]
        self.assertIn("Tài liệu nội bộ VLU", result["answer"])
        self.assertIn("Cần xin phép trước buổi học [1]", result["answer"])
        self.assertNotIn(WEB_TEXT, result["answer"])
        self.assertNotIn("private thought", json.dumps(result))
        self.assertEqual(result["grounding"], {
            "text": original, "search_suggestions_html": SUGGESTIONS,
            "sources": [{"url": WEB_URL, "title": "Bản tin thời tiết"}],
        })
        self.assertIn("document_id", result["sources"][0])
        request = self.sdk.call_args.kwargs
        self.assertEqual(request["contents"], PUBLIC)
        self.assertEqual(request["model"], "gemini-3.6-flash")
        self.assertIsNotNone(request["config"].tools[0].google_search)
        options = self.client_factory.call_args.kwargs["http_options"]
        self.assertEqual((options.timeout, options.retry_options.attempts), (12_000, 1))

        history = self.db.client.get(f"/conversations/{result['conversation_id']}/messages")
        self.assertEqual(history.status_code, 200)
        saved = history.json()
        self.assertEqual(saved[-1]["citations"], result["sources"])
        self.assertEqual(saved[-1]["content"], result["answer"] + "\n\n" + GROUNDING_EXPIRED)
        with self.db.sessions() as session:
            assistant = session.scalar(select(Message).where(Message.role == "assistant"))
            persisted = json.dumps({"content": assistant.content, "citations": assistant.citations}, ensure_ascii=False)
        for secret in ("private thought", WEB_URL, "provider-derived search query", SUGGESTIONS, WEB_TEXT):
            self.assertNotIn(secret, persisted)
        replay = self.stream(payload)[-1]["response"]
        self.assertEqual(replay["sources"], result["sources"])
        self.assertEqual(replay["answer"], saved[-1]["content"])
        self.assertNotIn("grounding", replay)
        self.sdk.assert_called_once()
        self.assertEqual(len(saved), 2)

        followup = "Chuyện khác là gì?"
        self.choose(routes=[("general", followup)])
        self.sdk.return_value = reply("Một câu trả lời chung.")
        self.ask(followup, conversation_id=result["conversation_id"])
        query_input = self.plan.call_args.args[0].to_string()
        self.assertIn(payload["question"], query_input)
        self.assertIn("Cần xin phép trước buổi học [1]", query_input)
        self.assertNotIn(WEB_TEXT, query_input)
        self.assertEqual(self.sdk.call_args.kwargs["contents"], followup)

    def test_http_grounding_no_store_and_history_keeps_only_expiry_notice(self):
        self.choose(routes=[("web", PUBLIC)])
        self.sdk.return_value = grounded()
        response = self.db.client.post("/questions", json={"question": PUBLIC})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        result = response.json()
        self.assertEqual(result["answer"], "")
        self.assertEqual(result["grounding"]["text"], WEB_TEXT)
        history = self.db.client.get(f"/conversations/{result['conversation_id']}/messages").json()
        self.assertEqual((history[-1]["content"], history[-1]["citations"]), (GROUNDING_EXPIRED, []))

    def test_history_and_replay_remove_legacy_grounding_from_storage(self):
        self.seed("Quy định VLU: xin phép nghỉ học trước buổi học.")
        self.choose(internal="Quy định nghỉ học VLU")
        self.db.model.return_value = RunnableLambda(lambda _: "Nội bộ nguyên vẹn [1].")
        for cleanup in ("history", "replay"):
            with self.subTest(cleanup=cleanup):
                payload = {"question": "Quy định nghỉ học VLU", "request_id": str(uuid4())}
                result = self.stream(payload)[-1]["response"]
                with self.db.sessions() as session:
                    row = session.scalar(select(Message).where(Message.role == "assistant",
                                                                 Message.conversation_id == UUID(result["conversation_id"])))
                    row_id = row.id
                    row.content += f"\n\n**Thông tin cập nhật từ web**\n\n{WEB_TEXT} [2]"
                    row.citations = [*row.citations, {"kind": "web", "citation": 2, "url": WEB_URL,
                                                    "title": "Nguồn cũ", "search_suggestions_html": SUGGESTIONS}]
                    session.commit()
                if cleanup == "history":
                    history = self.db.client.get(f"/conversations/{result['conversation_id']}/messages")
                    self.assertEqual(history.status_code, 200)
                    content, citations = (history.json()[-1][key] for key in ("content", "citations"))
                else:
                    replay = self.stream(payload)[-1]["response"]
                    content, citations = replay["answer"], replay["sources"]
                    self.assertNotIn("grounding", replay)
                self.assertEqual(content, result["answer"] + "\n\n" + GROUNDING_EXPIRED)
                self.assertEqual(citations, result["sources"])
                with self.db.sessions() as session:
                    row = session.get(Message, row_id)
                    self.assertEqual((row.content, row.citations), (content, citations))
        self.sdk.assert_not_called()

    def test_web_without_valid_attribution_or_on_provider_error_never_guesses(self):
        self.choose(routes=[("web", PUBLIC)])
        for response in (
            errors.ServerError(503, {"error": {"message": "provider private"}}),
            reply("Dự báo không có nguồn."),
            grounded(text=WEB_TEXT + " Buổi tối bão lớn."),
            grounded(suggestions=None),
            grounded(url="javascript:alert(1)"),
            grounded(text=WEB_TEXT + " https://invented.example.test"),
        ):
            with self.subTest(response=type(response).__name__):
                self.sdk.side_effect = response if isinstance(response, errors.APIError) else None
                self.sdk.return_value = response
                result = self.ask(PUBLIC)
                self.assertIn(WEB_UNAVAILABLE, result["answer"])
                self.assertEqual(result["sources"], [])
                self.assertNotIn("provider private", result["answer"])

        with patch.object(fixture.settings, "rag_google_search_enabled", False):
            self.sdk.reset_mock()
            self.assertIn(WEB_UNAVAILABLE, self.ask(PUBLIC)["answer"])
            self.sdk.assert_not_called()

    def test_mixed_general_and_partial_clarification_keep_the_internal_section(self):
        self.seed("Quy định VLU: xin phép trước khi nghỉ học.")
        self.db.model.return_value = RunnableLambda(lambda _: "Hãy xin phép trước [1].")
        internal = "Quy định nghỉ học VLU"
        question = "Vì sao bầu trời xanh?"
        self.choose(internal=internal, routes=[("general", question)])
        self.sdk.return_value = reply("Do tán xạ ánh sáng.")
        result = self.ask(f"{internal} và {question}")
        self.assertIn("Hãy xin phép trước [1]", result["answer"])
        self.assertIn("Kiến thức chung", result["answer"])
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(self.sdk.call_args.kwargs["contents"], question)

        weather = "Thời tiết hôm nay?"
        self.choose(internal=internal, routes=[("clarify", weather)])
        self.plan.return_value["external_parts"][0]["clarification"] = "Bạn muốn xem thời tiết ở đâu?"
        self.sdk.reset_mock()
        ambiguous = self.ask(f"{internal} và {weather}")
        self.assertIn("Hãy xin phép trước [1]", ambiguous["answer"])
        self.assertIn("Bạn muốn xem thời tiết ở đâu?", ambiguous["answer"])
        self.sdk.assert_not_called()

    def test_clarification_and_excerpts_that_fail_the_public_scope_check(self):
        self.plan.return_value = {"action": "clarify", "clarification": "Bạn muốn xem thời tiết ở đâu?"}
        self.assertEqual(self.ask("Thời tiết hôm nay?")["answer"], "Bạn muốn xem thời tiết ở đâu?")
        self.choose(routes=[("web", "thời tiết ở địa điểm model lấy từ lịch sử")])
        self.assertIn("nêu riêng", self.ask("Thời tiết hôm nay?")["answer"])
        internal = "Lịch nghỉ VLU tuần này"
        self.choose(routes=[("web", internal)])
        self.assertIn("Không có ngữ cảnh", self.ask(internal)["answer"])
        self.sdk.assert_not_called()

    def test_general_provider_failure_and_planner_failure_do_not_change_route(self):
        question = "Vì sao trời xanh?"
        self.choose(routes=[("general", question)])
        self.sdk.side_effect = TimeoutError("private provider detail")
        self.assertIn(GENERAL_UNAVAILABLE, self.ask(question)["answer"])
        self.sdk.assert_called_once()
        self.db.model.assert_not_called()

        self.sdk.reset_mock()
        self.plan.side_effect = errors.ServerError(503, {"error": {"message": "classification provider private"}})
        result = self.db.client.post("/questions", json={"question": question})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("provider private", result.text)
        self.sdk.assert_not_called()
