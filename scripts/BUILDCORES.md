# BuildCores import

Source: https://github.com/buildcores/buildcores-open-db

This database contains information from BuildCores OpenDB, made available under
the Open Data Commons Attribution License (ODC-By) v1.0:
https://opendatacommons.org/licenses/by/1-0/
Retain this attribution and the original license when redistributing data;
display attribution in public products using this dataset.

From the backend directory, run:

```powershell
.\.venv\Scripts\python.exe scripts/import_buildcores.py
```

This validates the complete checked-out snapshot and produces ignored
`import-output/parts.jsonl` and `report.json`. All source JSON is retained in
`parts.specs`; indexed names may be shortened to fit the existing schema.
Missing manufacturers use `Unknown`. Source commit and per-record URLs are recorded.
No prices are invented.

Before upload, execute `supabase/migrations/20260929_buildcores_categories.sql`
in Supabase SQL Editor. Set `SUPABASE_SECRET_KEY` (or legacy
`SUPABASE_SERVICE_ROLE_KEY`) in the ignored backend `.env`, then run:

```powershell
.\.venv\Scripts\python.exe scripts/import_buildcores.py --apply
```

After a successful dry run, add `--prepared` to reuse that snapshot with a
SHA-256 integrity check instead of rereading all source files.

Uploads use `external_id=buildcores:<source-category>:<opendb_id>` and upsert in batches. The source reuses four IDs across categories, so the category is part of the identity. Repeating
the command updates those records without inserting duplicates. Existing local
prices, images, descriptions and active flags are omitted from updates. No rows
are deleted. An interrupted import may be partial; rerun to finish. Every source
ID is checked against persisted records after upload; see `upload-result.json`.
