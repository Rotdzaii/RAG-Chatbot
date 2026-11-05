# Source metadata and explicit question filters

Sources use the existing nullable `documents.category` and `documents.audience`
columns. This feature needs no database migration. Both labels are free text;
there is no taxonomy and no scope inferred from the question or conversation.

## Enter and edit metadata

- `POST /documents`: optional multipart fields `category` and `audience`, alongside
  a PDF or TXT file.
- `POST /admin/knowledge-sources/url`: optional JSON fields `category` and `audience`,
  alongside `url`.
- `PATCH /admin/knowledge-sources/{source_id}/metadata`: an admin supplies one or
  both fields. Omitted fields keep their values; `null` or blank text clears a
  field. An empty patch or unknown field returns 422. A missing source returns
  404. This operation updates metadata without reindexing content.

New or edited labels use Unicode NFC and collapse whitespace. Case is preserved.
Replacing a file and refreshing a URL preserve the stored metadata and activation
state, including legacy labels that have not been normalized.

## List and retrieve sources

`GET /admin/knowledge-sources` accepts optional `category` and `audience` query
parameters, combined with the existing `source_type` and `is_active` filters.
Filtering applies to the count and the paginated results.

Both `POST /questions` and `POST /questions/stream` accept an optional `filters`
object:

```json
{
  "question": "What is the leave policy?",
  "filters": {"category": "policy", "audience": "staff"}
}
```

Only `category` and `audience` are accepted inside `filters`. Each supplied
non-null filter is normalized like a label and compared by exact, case-sensitive
equality. Blank filters and non-string values return 422. Null or omitted fields
add no predicate. A source with a null label does not match a supplied label.

Metadata predicates combine with `is_active = true` and the existing embedding
profile and distance checks in SQL before ordering and the top-k limit. The
candidate retrieval helper uses the same metadata and activation predicates.
Sources outside the scope cannot consume the top-k slots.

Omitting `filters`, sending `null`, or sending `{}` preserves unfiltered retrieval.
Each question supplies its own scope; a follow-up without filters does not inherit
the previous question's filters. The answer and citation response formats stay
unchanged, as do previously saved answers and citations.

SSE retries preserve the fingerprints of older requests without filters. Reusing
a request ID with different non-empty filters reports a conflict; normalized
equivalent filters replay the same result.

## Verification

`test_source_metadata.py` covers validation, admin permissions, upload plumbing,
list filters, metadata edits, and replacement/refresh preservation.
`test_metadata_retrieval.py` exercises the HTTP-to-retrieval flow, SQL predicates
before limits, activation, conversation scope, SSE retries, rollback, and file/URL
lifecycle behavior using isolated SQLite data, temporary file storage, and mocked
embedding, generation, and URL responses. No Gemini call or real database migration
is needed. These tests do not replace a PostgreSQL/pgvector integration check.

This change adds backend APIs only. It changes neither model configuration nor
embedding configuration, and includes no Admin UI, reranking, or benchmark changes.
