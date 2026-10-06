# P4 citation integrity, first offline step

The retriever keeps all candidates in `QuestionAnswer.sources` so P0/P1
retrieval metrics retain their original denominator. For generated answers,
`QuestionAnswer.cited_source_indices` stores the 1-based context numbers
actually present in the answer. The HTTP response and saved assistant message
include only those sources, preserving each original citation number (for
example, `[2]` still maps to source 2 even when source 1 is omitted).

Supported references follow the chat UI: `[1]`, `[1, 2]`, `[1; 2]`.
Markdown link labels such as `[1](https://example.com)` are ignored. A
reference to an unavailable source fails the question request before its
messages are committed; the existing API error response remains generic.
Answers without citation markers have no returned or persisted source entries.
The website reference panel also filters older stored conversations using the
answer's citation markers, so older rows do not display unused URLs.

This step verifies **reference indices and source selection**, not whether a
claim is actually supported by the referenced text. Such semantic support,
groundedness, and no-citation answer quality still require separately reviewed
evaluation cases. No provider call or prompt/model change is needed here.
