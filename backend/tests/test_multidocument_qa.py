"""Real retrieval, HTTP, citations and history over temporary SQLite; offline models."""

import json
import re
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from answer_fixture import GroundedModelStub
from answer_fixture import comparison_column
from sqlalchemy import delete, select

import test_source_activation as fixture
from rag.major_catalog import read_major_catalog, subject_name
from rag.models import Chunk, Document, Message, QuestionTurn
from rag.qa import answer_question
from rag.qa_diagnostics import QuestionDiagnostics
from rag.query_processing import process_query
from rag.retrieval import retrieve_chunks
from rag.source_metadata import RetrievalFilters


class MultiDocumentTests(unittest.TestCase):
    def setUp(self):
        self.db = fixture.SourceActivationTests()
        self.db.setUp()
        self.addCleanup(self.db.doCleanups)
        self.resolver = Mock()
        for target, value in (("rag.qa.process_query", process_query),
                              ("rag.query_processing._get_query_model", self.resolver)):
            p = patch(target, new=value)
            p.start()
            self.addCleanup(p.stop)
        self.structured = self.resolver.return_value.with_structured_output.return_value

    def seed(self, header, *, active=True, category="đào tạo", audience="SV", chunks=1, tilt=0.0):
        with self.db.sessions() as session:
            document = Document(
                filename="tên-không-liên-quan.pdf", mime_type="application/pdf",
                is_active=active, category=category, audience=audience,
                chunks=[Chunk(content=header if i == 0 else "Học phần thiết kế.",
                              chunk_index=i, page_start=i + 1, page_end=i + 1,
                              embedding=[1.0, tilt] + [0.0] * 766) for i in range(chunks)],
            )
            session.add(document)
            session.commit()
            return document.id

    def plan(self, majors, *, compare=False, topic="Học phần"):
        self.structured.invoke.return_value = {
            "action": "search", "scope": "compare" if compare else "answer",
            "standalone_query": f"{topic}: " + " và ".join(majors),
            "major_queries": [{"major": name, "question": f"{topic} của {name}?"} for name in majors],
            "comparison_criteria": [topic, "Học phí"] if compare else [],
        }

    def ask(self, question, **params):
        response = self.db.client.post("/questions", json={"question": question, **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_inventory_all_scoped_documents_with_real_history_and_no_model(self):
        a = self.seed("Tổng quan\nKiến trúc là ngành học về thiết kế.\nChuyên ngành: Nội thất")
        duplicate = self.seed("Ngành: KIẾN TRÚC\nCó nhắc đến ngành Y khoa.")
        b = self.seed("Ngành: Ngôn ngữ Nhật\nHọc phần: Ngữ âm")
        self.seed("Ngành: Y khoa", active=False)
        self.seed("Ngành: Du lịch", audience="GV")
        self.seed("Ngành: Âm nhạc", category="khác")
        with patch("rag.retrieval.embed_query") as embed:
            result = self.ask("VLU hiện có bao nhiêu ngành?", top_k=1,
                              filters={"category": "đào tạo", "audience": "SV"})
        self.assertIn("Theo các tài liệu hiện có, có 2 ngành:", result["answer"])
        self.assertIn("kiến trúc [1]", result["answer"].casefold())
        self.assertIn("Ngôn ngữ Nhật [2]", result["answer"])
        self.assertNotRegex(result["answer"], "Y khoa|Nội thất|Âm nhạc|Du lịch")
        first, second = result["sources"]
        self.assertIn(first["document_id"], [str(a), str(duplicate)])
        self.assertEqual(second["document_id"], str(b))
        self.assertEqual([row["citation"] for row in result["sources"]], [1, 2])
        self.assertIsNone(first["cosine_distance"])
        with self.db.sessions() as session:
            saved = session.scalar(select(Message).where(Message.role == "assistant"))
            self.assertEqual(saved.citations, result["sources"])
        self.resolver.assert_not_called()
        self.db.model.assert_not_called()
        embed.assert_not_called()
        # Two authenticated users see the same active corpus.
        self.db.as_user(uuid4())
        other = self.ask("VLU có những ngành nào?", filters={"category": "đào tạo", "audience": "SV"})
        self.assertEqual(other["sources"], result["sources"])

    def test_no_total_when_even_one_active_subject_is_unknown(self):
        self.seed("Ngành: Kiến trúc")
        self.seed("Quy chế thực tập\nVí dụ: ngành Hóa học.\nChuyên ngành: Hóa dầu.")
        self.seed("", chunks=0)
        result = self.ask("VLU hiện có bao nhiêu ngành?")
        self.assertIn("Chưa đủ bằng chứng", result["answer"])
        self.assertIn("Kiến trúc [1]", result["answer"])
        self.assertNotRegex(result["answer"], r"có \d+ ngành|Hóa")
        self.assertEqual(len(result["sources"]), 1)

    def test_inventory_trace_accounts_for_duplicate_unknown_and_missing_openings(self):
        known = self.seed("Ngành: Kiến trúc\nNội dung")
        another = self.seed("Ngành: KIẾN TRÚC")
        unknown = self.seed("Danh mục\nChuyên ngành: Đồ họa")
        no_chunk = self.seed("", chunks=0)
        self.seed("Ngành: Du lịch", active=False)
        trace = QuestionDiagnostics()
        with self.db.sessions() as session:
            answer = answer_question(session, "VLU có bao nhiêu ngành?", diagnostics=trace)
        by_doc = {row["document_id"]: row for row in trace.inventory}
        self.assertEqual(set(by_doc), set(map(str, (known, another, unknown, no_chunk))))
        self.assertEqual(by_doc[str(known)]["major"], "Kiến trúc")
        self.assertEqual(by_doc[str(another)]["recognition"], "subject_header")
        self.assertEqual(by_doc[str(unknown)]["content"], "Danh mục\nChuyên ngành: Đồ họa")
        self.assertIsNone(by_doc[str(unknown)]["major"])
        self.assertEqual(by_doc[str(unknown)]["recognition"], "unrecognized_declaration")
        self.assertEqual(by_doc[str(no_chunk)]["recognition"], "missing_opening_chunk")
        self.assertIsNone(by_doc[str(no_chunk)]["chunk_id"])
        self.assertEqual(trace.searches, [])
        self.assertIn("Chưa đủ bằng chứng", answer.answer)

    def test_major_code_at_rank_five_can_claim_a_context_slot_without_filler(self):
        major = "Marketing"
        overview = self.seed("Ngành: Marketing\nTrang chương trình tiêu chuẩn nêu một số học phần như "
                             "Kinh tế vi mô, Marketing căn bản, Hành vi tiêu dùng.")
        pdf = self.seed("Ngành: Marketing", chunks=14)
        self.seed(f"Ngành: {major}", audience="GV")
        self.seed(f"Ngành: {major}", active=False)
        majors = [major, "Kỹ thuật phần mềm", "Tài chính – Ngân hàng"]
        self.plan(majors, compare=True)
        criterion = "Mã ngành theo các tài liệu giới thiệu kỳ nhập học 2026"
        plan = self.structured.invoke.return_value
        plan["comparison_criteria"] = [criterion]
        plan["major_queries"] = [
            {"major": name, "question": f"Cho biết mã ngành của ngành {name} theo các tài liệu "
                                        "giới thiệu kỳ nhập học 2026 ở Cơ sở chính."} for name in majors
        ]
        question = "So sánh mã ngành của ba ngành theo kỳ nhập học 2026 ở Cơ sở chính."
        filters = RetrievalFilters(audience="SV")
        code_excerpt = "Văn bằng\nCử nhân Marketing\nMã ngành\n7340115\nKỳ nhập học\n2026\nCơ sở chính"
        # First five cosine distances and chunk positions from the three-majors diagnostic.
        # Rank 11 is within the threshold but outside the 10-candidate SQL limit.
        passages = [
            (overview, 0, .258353, None),
            (pdf, 13, .280679, "GIẢI ĐÁP\nMarketing học những gì?\nSinh viên học về nghiên cứu thị trường."),
            (pdf, 5, .282374, "Chương trình đào tạo và lộ trình học tập\nHọc phần Cơ sở ngành"),
            (pdf, 2, .282712, "Mục tiêu chương trình đào tạo Marketing"),
            (pdf, 1, .283137, code_excerpt),
            *((pdf, index, distance, None) for index, distance in
              [(7, .283588), (6, .286856), (3, .289409), (8, .289645), (0, .294569), (12, .295818)]),
            (pdf, 10, .307469, code_excerpt),
        ]

        def answer(prompt):
            context = prompt.to_messages()[-1].content.split("Question:")[0]
            self.assertEqual(context.count("Chunk index:"), 1)
            self.assertIn(code_excerpt, context)
            return comparison_column(["7340115 [1]"])

        model = Mock()
        model.with_structured_output.return_value = GroundedModelStub(answer)
        self.db.model.return_value = model
        with self.db.sessions() as session:
            chunks = {(chunk.document_id, chunk.chunk_index): chunk for chunk in session.scalars(select(Chunk))}
            for chunk in chunks.values():
                chunk.embedding = [0., 1.] + [0.] * 766
            for document_id, index, distance, content in passages:
                chunk = chunks[document_id, index]
                cosine = 1. - distance
                chunk.embedding = [cosine, (1. - cosine ** 2) ** .5] + [0.] * 766
                if content is not None:
                    chunk.content = content
            session.commit()
            trace = QuestionDiagnostics()
            with patch("rag.retrieval.embed_query", return_value=[1.] + [0.] * 767) as embed:
                observed = answer_question(session, question, filters=filters, diagnostics=trace)
            search, *skipped = trace.searches
            embed.assert_called_once_with(search.query)
            self.assertEqual((search.major, search.criterion), (major, criterion))
            self.assertEqual((search.candidate_limit, search.context_budget, search.max_distance), (10, 2, .30))
            self.assertEqual(search.query.count(major), 1)
            self.assertEqual(search.query.count("2026"), 1)
            self.assertEqual(search.query.count("mã ngành"), 1)
            self.assertIn("Cơ sở chính", search.query)
            self.assertEqual([s.status for s in skipped], ["no_identified_document"] * 2)
            self.assertEqual([c["chunk_index"] for c in search.candidates[:5]], [0, 13, 5, 2, 1])
            self.assertEqual([c["decision"] for c in search.candidates[:4]], ["criterion_not_supported"] * 4)
            code_hit = search.candidates[4]
            self.assertEqual((code_hit["rank"], code_hit["retrieved_rank"], code_hit["citation"]), (5, 5, 1))
            self.assertAlmostEqual(code_hit["cosine_distance"], .283137, places=6)
            self.assertEqual(code_hit["decision"], "selected")
            self.assertEqual(search.candidates[10]["decision"], "outside_retrieval_budget")
            self.assertEqual(search.candidates[11]["decision"], "above_threshold")
            self.assertIn("7340115 [1]", observed.answer)
            self.assertEqual([(s.document_id, s.chunk_index) for s in observed.sources], [(pdf, 1)])

            for replacement in ("Thông tin học phần", code_excerpt.replace("2026", "2025")):
                with self.subTest(replacement=replacement):
                    chunks[pdf, 1].content = replacement
                    session.commit()
                    self.db.model.reset_mock()
                    trace = QuestionDiagnostics()
                    with patch("rag.retrieval.embed_query", return_value=[1.] + [0.] * 767):
                        missing = answer_question(session, question, filters=filters, diagnostics=trace)
                    self.assertEqual(missing.answer.count("Chưa đủ thông tin"), 3)
                    self.assertEqual(missing.sources, [])
                    self.assertEqual(trace.searches[0].candidates[4]["decision"], "criterion_not_supported")
                    self.db.model.assert_not_called()

    def test_undecomposed_query_traces_the_actual_pipeline_search(self):
        document_id = self.seed("Quy định thư viện")
        self.structured.invoke.return_value = {"action": "search", "standalone_query": "Quy định thư viện"}
        self.db.model.return_value = GroundedModelStub(lambda _: "Quy định thư viện [1]")
        trace = QuestionDiagnostics()
        with self.db.sessions() as session:
            answer = answer_question(session, "Thư viện có quy định gì?", diagnostics=trace)
        search, = trace.searches
        self.assertEqual((search.status, search.query), ("searched", answer.rewritten_query))
        candidate, = search.candidates
        self.assertEqual((candidate["document_id"], candidate["decision"], candidate["citation"]),
                         (str(document_id), "selected", 1))
        self.assertEqual(answer.cited_source_indices, (1,))

    def test_only_opening_declarations_identify_a_document(self):
        for text in ("Quy định\nVí dụ\nNgành: Y khoa", "Chuyên ngành: Đồ họa",
                     "Tổng quan\nChuyên ngành Đồ họa là ngành học mới.",
                     "Ngành: Y khoa\nNgành: Âm nhạc"):
            with self.subTest(text=text):
                self.assertIsNone(subject_name(text))
        self.assertEqual(subject_name("Tổng quan\nDesign (Thiết kế) là ngành học về tạo hình."), "Design")
        self.assertEqual(subject_name("Trường: Đại học Văn Lang\nNgành: Âm nhạc\nPhạm vi: K32"), "Âm nhạc")

    def test_inventory_normalizes_spelling_but_preserves_question_qualifiers(self):
        self.seed("Ngành: Tài chính – Ngân hàng")
        self.seed("Ngành: TÀI CHÍNH-NGÂN HÀNG")
        result = self.ask("VLU có bao nhiêu ngành?")
        self.assertIn("có 1 ngành:", result["answer"])
        self.structured.invoke.return_value = {"action": "clarify", "clarification": "Bạn muốn xét năm nào?"}
        result = self.ask("VLU có bao nhiêu ngành đạt kiểm định năm 2025?")
        self.assertEqual(result["sources"], [])
        self.structured.invoke.assert_called_once()

    def test_source_replacement_between_planning_and_search_cannot_leak_into_old_group(self):
        doc_id = self.seed("Ngành: Kiến trúc")
        with self.db.sessions() as session:
            ids = read_major_catalog(session, None).majors["kiến trúc"].header_ids
            session.execute(delete(Chunk).where(Chunk.document_id == doc_id))
            session.add(Chunk(document_id=doc_id, chunk_index=0, content="Ngành: Luật",
                              embedding=[1.0] + [0.0] * 767))
            session.commit()
            self.assertEqual(retrieve_chunks(session, "Học phí", subject_headers=tuple(ids)), [])

    def test_global_top_hits_are_one_major_yet_both_receive_cited_answers(self):
        a = self.seed("Ngành: Kiến trúc\nHọc phần: Đồ án", chunks=7)
        b = self.seed("Ngành: Ngôn ngữ Nhật\nHọc phần: Ngữ âm", tilt=0.3)
        with self.db.sessions() as session:
            for chunk in session.scalars(select(Chunk).where(Chunk.document_id == a, Chunk.chunk_index > 0)):
                chunk.embedding = [1.0, .05] + [0.0] * 766
            session.commit()
            self.assertEqual({r.document_id for r in retrieve_chunks(session, "Môn học", 5)}, {a})
        self.plan(["Kiến trúc", "Ngôn ngữ Nhật"])
        contexts = []

        def reply(prompt):
            context = prompt.to_messages()[-1].content
            contexts.append(context)
            citation = re.search(r"\[(\d+)\]", context)[0]
            return ("Ngữ âm " if "Ngữ âm" in context else "Đồ án ") + citation

        self.db.model.return_value = GroundedModelStub(reply)
        result = self.ask("Cho vài môn học của Kiến trúc và Ngôn ngữ Nhật.")
        self.assertIn("Đồ án [1]", result["answer"])
        self.assertIn("Ngữ âm [4]", result["answer"])
        self.assertEqual([row["document_id"] for row in result["sources"]], [str(a), str(b)])
        self.assertEqual([row["chunk_index"] for row in result["sources"]], [0, 0])
        self.assertIn("Học phần: Đồ án", contexts[0])
        self.assertIn("Học phần: Ngữ âm", contexts[1])
        self.assertNotIn("Ngữ âm", contexts[0])
        self.assertNotIn("Kiến trúc", contexts[1])
        self.assertLessEqual(sum(text.count("Chunk index:") for text in contexts), 5)

    def test_comparison_uses_each_majors_own_evidence_per_criterion(self):
        self.seed("Ngành: Kiến trúc\nHọc phần: Đồ án")
        self.seed("Ngành: Ngôn ngữ Nhật\nHọc phần: Ngữ âm")
        self.plan(["Kiến trúc", "Ngôn ngữ Nhật"], compare=True)
        structured = Mock()
        structured.with_structured_output.return_value = GroundedModelStub(
            lambda prompt: comparison_column(["Đồ án [1]", None] if "Đồ án" in prompt.to_messages()[-1].content
                                                else ["Ngữ âm [2]", None])
        )
        self.db.model.return_value = structured
        result = self.ask("So sánh học phần và học phí hai ngành.")
        self.assertIn("| Học phần | Đồ án [1] | Ngữ âm [2] |", result["answer"])
        self.assertEqual(result["answer"].count("Chưa đủ thông tin"), 2)
        self.assertEqual(len(result["sources"]), 2)
        with self.db.sessions() as session:
            turn = session.scalar(select(QuestionTurn))
            self.assertEqual((turn.outcome, turn.reasons), ("partial", ["missing_evidence"]))

    def test_distinct_scoped_passages_are_retrieved_for_each_comparison_cell(self):
        majors = ["Kiến trúc", "Ngôn ngữ Nhật"]
        facts = [("Đồ án", "12 triệu"), ("Ngữ âm", "15 triệu")]
        expected = {}
        for name, (course, fee) in zip(majors, facts):
            expected[course] = self.seed(f"Ngành: {name}\nK32 học {course}.", audience="K32")
            expected[fee] = self.seed(f"Ngành: {name}\nHọc phí K32 là {fee}.", audience="K32", tilt=10)
            self.seed(f"Ngành: {name}\nHọc phí K31 là 99 triệu.", audience="K31", tilt=10)
        self.plan(majors, compare=True)
        for part in self.structured.invoke.return_value["major_queries"]:
            part["question"] = f"Theo đề cương khóa K32 của ngành {part['major']}?"
        searches = []

        def vector(query):
            searches.append(query)
            return ([0., 1.] if "học phí" in query.casefold() else [1., 0.]) + [0.] * 766

        def answer(prompt):
            passages = prompt.to_messages()[-1].content.split("Question:")[0]
            cells = [None, None]
            for number, content in re.findall(r"\[(\d+)\]\nFilename:.*?Content:\n(.*?)(?=\n\n\[|\Z)",
                                              passages, re.S):
                for course, fee in facts:
                    for index, value in enumerate((course, fee)):
                        if value in content:
                            cells[index] = f"{value} [{number}]"
            return comparison_column(cells)

        model = Mock()
        model.with_structured_output.return_value = GroundedModelStub(answer)
        self.db.model.return_value = model
        with patch("rag.retrieval.embed_query", side_effect=vector):
            result = self.ask("So sánh học phần và học phí khóa K32 của Kiến trúc và Ngôn ngữ Nhật.",
                              filters={"audience": "K32"})
        cited = {row["citation"]: row["document_id"] for row in result["sources"]}
        for fact, document in expected.items():
            match = re.search(rf"{fact} \[(\d+)\]", result["answer"])
            self.assertIsNotNone(match, fact)
            self.assertEqual(cited[int(match[1])], str(document))
        for name in majors:
            for criterion in ("Học phần", "Học phí"):
                self.assertTrue(any(name in q and criterion in q and "K32" in q for q in searches))
        self.assertNotIn("99 triệu", result["answer"])

        # One passage per major. The fee passages passed retrieval but could
        # not fit. Distinguish that from a corpus with no relevant fee evidence.
        model.with_structured_output.return_value = GroundedModelStub(
            lambda p: comparison_column(answer(p).cells[:1]))
        with patch("rag.retrieval.embed_query", side_effect=vector):
            limited = self.ask("So sánh học phần và học phí khóa K32.", top_k=2, filters={"audience": "K32"})
        self.assertEqual(limited["answer"].count("Chưa đủ ngân sách"), 2)
        self.assertIn("| Học phần | Đồ án [1] | Ngữ âm [2] |", limited["answer"])
        self.assertEqual([r["document_id"] for r in limited["sources"]],
                         [str(expected["Đồ án"]), str(expected["Ngữ âm"])])

        # The course and fee indices both exist within major A. Swapping them
        # must fail even though both indices pass the global range check.
        model.with_structured_output.return_value = GroundedModelStub(
            lambda _: comparison_column(["Đồ án [2]", "12 triệu [1]"]))
        with patch("rag.retrieval.embed_query", side_effect=vector):
            invalid = self.db.client.post("/questions", json={"question": "So sánh hai tiêu chí K32",
                                                             "filters": {"audience": "K32"}})
        self.assertEqual(invalid.status_code, 503)

    def test_three_and_four_majors_select_their_own_courses_without_filling_from_far_hits(self):
        majors = {"Kiến trúc": "Đồ án", "Ngôn ngữ Nhật": "Ngữ âm", "Âm nhạc": "Hòa âm", "Du lịch": "Lữ hành"}
        expected = {}
        for name, course in majors.items():
            expected[name] = self.seed(f"Ngành: {name}\nHọc phần: {course}")
            self.seed(f"Ngành: {name}\nĐịa chỉ văn phòng", tilt=5.0)
        prompts = []

        def answer(prompt):
            context = prompt.to_messages()[-1].content.split("Question:")[0]
            prompts.append(context)
            self.assertNotIn("văn phòng", context)
            course = re.search(r"Học phần: ([^\n]+)", context)[1]
            return course + " " + re.search(r"\[\d+\]", context)[0]

        self.db.model.return_value = GroundedModelStub(answer)
        for count in (3, 4):
            with self.subTest(count=count):
                names = list(majors)[:count]
                prompts.clear()
                self.plan(names)
                result = self.ask("Môn học của " + ", ".join(names) + "?")
                self.assertEqual(sum(p.count("Chunk index:") for p in prompts), count)
                for index, name in enumerate(names, 1):
                    self.assertIn(f"**{name}**\n\n{majors[name]} [{index}]", result["answer"])
                    self.assertEqual(result["sources"][index - 1]["document_id"], str(expected[name]))

    def test_small_budget_prefers_passage_supporting_two_criteria_and_names_the_gap(self):
        names = ["Kiến trúc", "Ngôn ngữ Nhật"]
        sheets = [self.seed(f"Ngành: {name}\nMã ngành: 750000{i}, thời gian {i} năm.") for i, name in enumerate(names, 1)]
        self.seed("Ngành: Kiến trúc\nHọc phí: 12 triệu.", tilt=10)
        self.plan(names, compare=True, topic="Theo bản giới thiệu")
        self.structured.invoke.return_value["comparison_criteria"] = ["Học phí", "Mã ngành", "Thời gian"]

        def respond(prompt):
            context = prompt.to_messages()[-1].content.split("Question:")[0]
            number, code, duration = re.search(r"\[(\d+)\].*?Mã ngành: (\d{7}), thời gian (\d+ năm)", context, re.S).groups()
            return comparison_column([f"{code} [{number}]", f"{duration} [{number}]"])

        model = Mock()
        model.with_structured_output.return_value = GroundedModelStub(respond)
        self.db.model.return_value = model
        trace = QuestionDiagnostics()
        question = "So sánh học phí, mã ngành và thời gian."
        with patch("rag.retrieval.embed_query", side_effect=lambda q:
                   ([0., 1.] if q.startswith("Học phí") else [1., 0.]) + [0.] * 766):
            result = self.ask(question, top_k=2)
            with self.db.sessions() as session:
                observed = answer_question(session, question, top_k=2, diagnostics=trace)
        self.assertEqual(observed.answer, result["answer"])
        fees = {s.major: s.candidates for s in trace.searches if s.criterion == "Học phí"}
        fee_hit = next(c for c in fees[names[0]] if c["retrieved_rank"] == 1)
        self.assertEqual((fee_hit["decision"], fee_hit["citation"]), ("outside_context_budget", None))
        self.assertEqual([c["decision"] for c in fees[names[1]]], ["above_threshold"])
        for s in trace.searches:
            if s.criterion in ("Mã ngành", "Thời gian"):
                self.assertEqual(s.candidates[0]["citation"], names.index(s.major) + 1)
                self.assertEqual(s.candidates[0]["decision"], "selected")
        self.assertIn("| Học phí | Chưa đủ ngân sách đoạn trích để trả lời tiêu chí này. "
                      "| Chưa đủ thông tin trong các tài liệu đang sử dụng. |", result["answer"])
        self.assertIn("| Mã ngành | 7500001 [1] | 7500002 [2] |", result["answer"])
        self.assertIn("| Thời gian | 1 năm [1] | 2 năm [2] |", result["answer"])
        self.assertEqual([r["document_id"] for r in result["sources"]], list(map(str, sheets)))

    def test_declaration_in_later_chunk_does_not_complete_inventory(self):
        known = self.seed("Ngành: Kiến trúc")
        unknown = self.seed("Quy định về học phần")
        with self.db.sessions() as session:
            session.add(Chunk(document_id=unknown, chunk_index=1, content="Ngành: Du lịch",
                              embedding=[1.0] + [0.0] * 767))
            session.commit()
        result = self.ask("VLU có bao nhiêu ngành?")
        self.assertIn("Chưa đủ bằng chứng", result["answer"])
        self.assertNotRegex(result["answer"], r"có \d+ ngành|Du lịch")
        self.assertEqual([r["document_id"] for r in result["sources"]], [str(known)])

    def test_partial_answer_if_b_is_absent_disabled_or_below_threshold(self):
        a = self.seed("Ngành: Kiến trúc\nHọc phần: Đồ án")
        self.seed("Ngành: Ngôn ngữ Nhật", active=False)
        self.seed("Ngành: Ngôn ngữ Nhật", tilt=3.0)
        self.seed("Ngành: Ngôn ngữ Nhật", category="khác")
        self.plan(["Kiến trúc", "Ngôn ngữ Nhật", "Âm nhạc"])
        self.db.model.return_value = GroundedModelStub(lambda _: "Đồ án [1]")
        result = self.ask("Môn học của ba ngành?", filters={"category": "đào tạo"})
        self.assertIn("**Kiến trúc**\n\nĐồ án [1]", result["answer"])
        for name in ("Ngôn ngữ Nhật", "Âm nhạc"):
            self.assertIn(f"**{name}**\n\nChưa đủ thông tin", result["answer"])
        self.assertEqual([row["document_id"] for row in result["sources"]], [str(a)])

    def test_uncited_private_claims_and_oversized_legacy_context(self):
        self.seed("Ngành: Kiến trúc\n" + "x" * 2000 + "OUTSIDE_BUDGET")
        self.plan(["Kiến trúc"])

        def unsupported(prompt):
            self.assertNotIn("OUTSIDE_BUDGET", prompt.to_messages()[-1].content)
            return "Học phí là 15 triệu."

        self.db.model.return_value = GroundedModelStub(unsupported)
        result = self.ask("Học phí ngành Kiến trúc?")
        self.assertIn("Chưa đủ thông tin", result["answer"])
        self.assertNotIn("15 triệu", result["answer"])
        self.assertEqual(result["sources"], [])

    def test_switch_followup_and_ambiguous_referent_use_owned_history(self):
        self.seed("Ngành: Kiến trúc")
        b = self.seed("Ngành: Ngôn ngữ Nhật")
        self.plan(["Kiến trúc"])
        conversation = self.ask("Ngành Kiến trúc học gì?")["conversation_id"]
        # Even a stale provider rewrite carrying A cannot redirect an explicit switch to B.
        result = self.ask("Còn ngành Ngôn ngữ Nhật?", conversation_id=conversation)
        self.assertEqual([row["document_id"] for row in result["sources"]], [str(b)])
        self.plan(["Ngôn ngữ Nhật"])
        result = self.ask("Ngành đó học gì?", conversation_id=conversation)
        self.assertEqual([row["document_id"] for row in result["sources"]], [str(b)])
        self.plan(["Kiến trúc", "Ngôn ngữ Nhật"])
        self.db.model.return_value = GroundedModelStub(lambda p: re.search(r"\[\d+\]", p.to_messages()[-1].content)[0])
        self.ask("Nêu môn học của Kiến trúc và Ngôn ngữ Nhật", conversation_id=conversation)
        self.plan(["Kiến trúc"])  # Resolver guesses one of two equally plausible referents.
        self.db.model.reset_mock()
        result = self.ask("Ngành đó học gì?", conversation_id=conversation)
        self.assertIn("ngành nào", result["answer"])
        self.assertEqual(result["sources"], [])
        self.db.model.assert_not_called()
        prompt = self.structured.invoke.call_args.args[0].to_messages()[-1].content
        self.assertIn("Nêu môn học của Kiến trúc và Ngôn ngữ Nhật", prompt)

    def test_budget_and_cross_major_citations_do_not_publish_invalid_answers(self):
        self.seed("Ngành: Kiến trúc")
        self.seed("Ngành: Ngôn ngữ Nhật")
        self.plan(["Kiến trúc", "Ngôn ngữ Nhật"])
        result = self.ask("Học phí hai ngành?", top_k=1)
        self.assertIn("ưu tiên", result["answer"])
        self.db.model.assert_not_called()
        contexts = []

        def wrong_major(prompt):
            contexts.append(prompt.to_messages()[-1].content.split("Question:")[0])
            return "Học phí [1]."

        self.db.model.return_value = GroundedModelStub(wrong_major)
        response = self.db.client.post("/questions", json={"question": "Học phí hai ngành?"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("[1]", contexts[0])
        self.assertIn("Ngành: Kiến trúc", contexts[0])
        self.assertIn("[2]", contexts[1])
        self.assertIn("Ngành: Ngôn ngữ Nhật", contexts[1])
        self.assertNotIn("[1]", contexts[1])
        with self.db.sessions() as session:
            self.assertEqual(len(session.scalars(select(Message)).all()), 2)

    def test_inventory_via_sse_preserves_citations(self):
        self.seed("Ngành: Kiến trúc")
        response = self.db.client.post("/questions/stream", json={
            "question": "VLU có bao nhiêu ngành?", "request_id": str(uuid4()),
        })
        self.assertEqual(response.status_code, 200)
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual([f["stage"] for f in frames if "stage" in f], ["query", "retrieval", "validation"])
        self.assertEqual(frames[-1]["response"]["sources"][0]["page_start"], 1)
