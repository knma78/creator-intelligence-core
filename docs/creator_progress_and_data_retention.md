# Creator Progress and Data Retention

## Persistent creator progress

Creator crawl progress is stored in:

```text
state/creator_progress.sqlite3
```

This database is intentionally outside `cache/` and `output/`, and `state/` is
ignored by Git. It stores the creator identity, the ordered list of discovered
video IDs, the crawl horizon, and each video's processing state:

- `queued`: discovered and waiting to be analyzed;
- `processing`: currently being analyzed; a restart makes it eligible again;
- `analyzed`: analysis completed successfully;
- `failed`: analysis failed and can be retried.

The queue is ordered by first discovery. New videos are appended, so a later
batch resumes the next queued video instead of depending on a disposable media
file or a shifting platform page number. Progress means analysis completed; it
does not mean a creative rule was human-validated.

When the Web app starts, it imports successful IDs from existing creator
indexes and batch manifests before they are overwritten. The migration only
trusts successful outputs; legacy platform-wide skipped IDs are not attributed
to an individual creator. Run the updated app once before deleting legacy
creator output folders if their progress should be migrated.

## Safe cleanup boundary

Use the Knowledge System's Data Protection panel for verified snapshots,
isolated restore drills and reversible index quarantine. See
[Data protection and version-bound reviews](data_protection.md) for scope,
excluded assets and recovery limitations. This does not automatically purge media.

Downloaded media can be removed after analysis without deleting the progress
database. Keep `state/creator_progress.sqlite3` to resume in order.

Knowledge rebuilds still use research artifacts under `output/<video_id>`.
Keep at least `analysis.json`, `subtitle.txt`, and `v3.json` if you want to
rebuild the lexical knowledge index and rule evidence. The generated indexes in
`cache/` are rebuildable only while those source artifacts remain. Keep
`output/creator_knowledge_base/rules/rule_reviews.json` if you have entered
human reviews; those reviews are not inferred again from video files.

Do not treat deleting the entire `output/` or `cache/` directory as equivalent
to deleting downloaded video files. Those folders also contain analysis
evidence and generated knowledge snapshots.

## Knowledge status

The creator rules remain conditional candidates until reviewed. A candidate
shown in a script plan is guidance only: the planner can suggest and compare
abilities, but does not rewrite the script or promote a rule to `validated`.
