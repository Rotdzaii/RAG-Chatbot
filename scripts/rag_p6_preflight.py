"""Offline P6 readiness checks; imports no database or provider code."""

from __future__ import annotations

from datetime import datetime, timezone

from rag_snapshot import snapshot_summary, validate_snapshot
from validate_rag_eval_manifest import manifest_summary, validate_manifest


def build_preflight_report(
    snapshot: object,
    manifests: list[tuple[str, object]],
) -> dict[str, object]:
    snapshot_errors = validate_snapshot(snapshot)
    snapshot_info = (
        snapshot_summary(snapshot) if not snapshot_errors and isinstance(snapshot, dict)
        else None
    )
    manifest_results: list[dict[str, object]] = []
    for name, manifest in manifests:
        errors = (
            ["snapshot invalid; manifest evidence not checked"]
            if snapshot_errors else validate_manifest(manifest, snapshot)
        )
        try:
            counts = manifest_summary(manifest)
        except ValueError:
            counts = None
        approved = counts["approved"] if counts is not None else 0
        manifest_results.append({
            "manifest": name,
            "fingerprint": (
                manifest.get("snapshot", {}).get("fingerprint")
                if isinstance(manifest, dict) and isinstance(manifest.get("snapshot"), dict)
                else None
            ),
            "review": counts,
            "status": (
                "invalid" if errors else "pending_review" if approved == 0
                else "ready_for_live_compatibility_check"
            ),
            "errors": errors,
        })
    ready = (
        not snapshot_errors
        and bool(manifest_results)
        and all(item["status"] == "ready_for_live_compatibility_check" for item in manifest_results)
    )
    return {
        "schema_version": "1.0",
        "phase": "P6",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_for_live_compatibility_check" if ready else "blocked",
        "scope": "offline_manifest_and_snapshot_only",
        "live_corpus_verified": False,
        "quality_score": None,
        "snapshot": {"status": "valid" if not snapshot_errors else "invalid",
                     "summary": snapshot_info, "errors": snapshot_errors},
        "manifests": manifest_results,
    }
