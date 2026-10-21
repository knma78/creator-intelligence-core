# Public source and private data boundary

This repository distributes program code, dependency definitions, generic
configuration schemas, documentation and synthetic tests. It does not ship a
learned knowledge corpus or finished creative works.

## Keep local

- Research sources, transcripts, creator selections and profiles.
- Observations, learned rules, evidence, human reviews and their version history.
- Knowledge indexes, embeddings, databases, progress records and job history.
- Credentials, cookies, browser profiles, local paths and machine configuration.
- Generated narration, storyboards, videos, slides, documents and CapCut drafts.
- Model weights, cached downloads, backups and restore directories.
- Local handoff notes and validation records referring to finished works.

The main runtime directories `output`, `cache`, `state`, `logs`, `backups` and
`restores` are ignored. Generic capability classification and processing code
remain public; personal observations and learned results do not.

The public creator defaults are empty. Copy `tools/creator_specs.example.json`
to `tools/creator_specs.json` locally, then configure your own selections.
Never commit the resulting personal file.

Synthetic test fixtures are deliberately non-production data. They are not
validated creative samples, third-party research evidence or reusable media.

## Before publishing

1. Review the entire staged file list, including files already tracked.
2. Inspect staged diffs for credentials, machine identifiers, copied knowledge
   records and any creative output embedded in source code or documentation.
3. Reject unexpected media, archives, databases and generated artifacts.
4. Run tests from a clean public checkout without the author's private data.
5. Check all commits to be pushed, not just the last working-tree diff.

`.gitignore` does not remove tracked files or erase previous commits.
Removing a file in the latest revision does not remove it from earlier public
history. History rewriting and credential revocation require a separate review;
this release does not claim to have erased older public copies.
