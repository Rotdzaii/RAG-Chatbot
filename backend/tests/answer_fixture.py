"""Deterministic chat model stub for the grounded-answer schema."""

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


def comparison_column(cells):
    from rag.langchain_pipeline import ComparisonColumn, GroundedAnswer

    return ComparisonColumn(cells=[
        cell if isinstance(cell, GroundedAnswer) else GroundedAnswer(
            outcome="answered" if cell is not None else "insufficient_evidence", answer=cell or ""
        )
        for cell in cells
    ])


class GroundedModelStub(RunnableLambda):
    def with_structured_output(self, schema):
        from rag.langchain_pipeline import GroundedAnswer

        if schema is not GroundedAnswer:
            raise AssertionError("Unexpected test model schema")

        def respond(prompt):
            result = self.func(prompt)
            if isinstance(result, GroundedAnswer):
                return result
            answer = result.content if isinstance(result, AIMessage) else result
            return GroundedAnswer(outcome="answered", answer=answer)

        return RunnableLambda(respond)
