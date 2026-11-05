# URL source change notifications (retired)

The Admin notification page, notification read/list APIs, URL change checker and
`scripts/check_url_source_changes.py` have been removed. No remaining runtime
caller uses the checker. This branch adds no scheduler or replacement polling.

Admin still imports URLs with `POST /admin/knowledge-sources/url` and explicitly
refreshes a stored URL with `POST /admin/knowledge-sources/{source_id}/refresh`.
The UI keeps **Add source** and **Update URL**, including `updated`/`unchanged`
results, validation and error handling. Metadata and activation state survive
manual refresh. Existing `/admin/notifications` bookmarks redirect to the source
catalog and continue through its usual admin access check.

## Existing databases and migration history

All existing migration files are unchanged. Revision `f9d4b2c7e501` still follows
`b6c8d0e2f4a1`; revision `c2a1e8d4f6b0` still follows `f9d4b2c7e501`. There is no
new migration and no table or data removal as part of this retirement.

The legacy `SourceChangeNotification` mapping and document relationship remain to
match the existing table and preserve normal cascade behavior when deleting a
source. They do not expose a notification API or create new notifications. Keeping
them also prevents Alembic autogenerate from proposing an accidental table drop.
`content_hash` and `last_checked_at` remain in use by ingestion and manual refresh.

The exported HTML under `docs/ui-reference/` is a historical layout reference,
not an Admin route; its old notification mockup is retained as an original asset.

## Isolated verification

`backend/tests/test_url_notifications_retirement.py` checks that the removed APIs
return 404, new URL import/manual refresh still work with fake URL bytes, failed
refresh preserves the indexed corpus, legacy rows remain intact, and the original
migration chain and table constraints remain valid. Database operations use
SQLite in temporary storage, never a configured real database.

Frontend browser tests mock Auth and API requests, verify that desktop/mobile
navigation has no notification entry and old bookmarks open the source catalog,
and retain URL import/update, permissions, chat, history and citation coverage.
