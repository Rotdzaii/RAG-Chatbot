# P3 case review: Kỹ thuật phần mềm

`evals/cases/software_p3_draft.json` contains 10 candidate cases tied to the
user's 5-document snapshot `software_p2_20261006.json` (SHA-256
`a63d20c231e4950683bd109a97101d018510c2fe3577a0d5c5836a5010a59aec`).
All 10 have `pending_review`, `answerability=unknown`; **none is a gold case**.

| Cases | Purpose | Retrieval probe |
| --- | --- | --- |
| 001–005 | Duration, directions, FAQ content, first-year examples, game career | Candidate after review |
| 006 | Cross-major comparison requiring both Marketing and software evidence | Candidate after review |
| 007 | Typo in major name | Candidate after review |
| 008 | Follow-up referring to software engineering | Use P1 multi-turn evaluation |
| 009 | Missing major; ask a clarification question | Not applicable |
| 010 | Exact 2027 tuition absent; refrain from guessing | Not applicable |

Before approval, a reviewer must inspect each exact quote against the stored
chunk and the source PDF, check that the question is answerable under the
snapshot, settle the expected behavior, and assign applicability/reviewer/time.
The year-2027 tuition case is in scope as a question but has no verified answer
for that year; the PDF's current tuition range must not be treated as its answer.
The FAQ heading about AI and jobs is only a question in the extracted PDF.

The uploaded snapshot predates some code/configuration changes. Export a fresh
snapshot from the **merged** backend before a live run. If its fingerprint
differs, review the document/chunk IDs, text, embedding configuration, and
evidence again and create a newly reviewed manifest for that exact snapshot.
Changing only the fingerprint does not transfer approval. The live probe
will reject a mismatched snapshot before it calls the embedding provider.
