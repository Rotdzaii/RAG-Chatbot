# P3 retrieval probe

This probe measures retrieval only. It calls the query embedding once per approved,
independent question, reads up to 20 compatible chunks, and reuses their distances
to evaluate 15 combinations: thresholds 0.20–0.40 and `top_k` 3, 5, 10.
The production setting remains threshold 0.30 and `top_k` 5. It does not
call answer generation or query rewriting, mutate the corpus, or save vectors.

## Preconditions

- The manifest must pass `validate_rag_eval_manifest.py` against the given
  snapshot. Approval is tied to that exact fingerprint and its chunk IDs.
- Live execution exports a read-only snapshot and requires an exact fingerprint
  match **before** calling the embedding provider. Snapshot validation covers
  embedding presence/dimensions, not the full vector values.
- The approved Marketing P0 manifest belongs to the older `current.json` snapshot
  (`3ff169ac...`). It **cannot** be scored against the newer 5-document software
  snapshot (`a63d20c2...`). Review evidence on the new snapshot and approve a
  separate manifest first. Merely editing the fingerprint would be invalid.
- Follow-ups require query processing and are excluded here, as are questions
  without applicable retrieval evidence. Evaluate those with the P1 runner.

## Commands (PowerShell, from repository root)

```powershell
Push-Location backend
uv run --locked --no-sync python ../scripts/run_rag_retrieval_probe.py `
  ../evals/cases/marketing_p0.json `
  --snapshot ../data/rag_snapshots/current.json `
  --output ../data/rag_runs/retrieval_probe_dry.json --dry-run
Pop-Location
```

For a live probe, substitute a **new reviewed manifest** and its matching
current snapshot, choose a fresh output path, and omit `--dry-run`. Use
`--case-id ID` for a single selected case. The CLI refuses an existing output
unless explicitly given `--overwrite`; an error stops further embedding calls,
writes an incomplete artifact, and exits with code 3.

Read the per-case candidates and `scenario_aggregates` in the resulting JSON.
Compare the 0.30/5 row with alternatives only when the run is complete. Retrieval
metrics measure evidence chunk IDs, not answer correctness; generation and
citation quality still need their separate review. Do not pick a threshold
solely from this small pilot and assume it generalizes across majors.
