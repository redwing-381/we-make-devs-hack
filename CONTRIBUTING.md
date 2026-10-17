# Working on Why-Graph

There are three of us and about 30 hours, so the workflow is built for parallel work with no merge pain.

## Flow

1. Read your section of [docs/work-split.md](docs/work-split.md), then pick your next row in
   [docs/features.md](docs/features.md). Owners: **A** Shoban (Graph & Memory), **B** Solai (Agents &
   Integrations), **C** Sakthi (UI, demo app & deploy).
2. Branch from fresh `main`:
   ```bash
   git switch main && git pull && git switch -c feat/<name>
   ```
3. Commit small and often, using conventional messages: `feat(graph): add blast_radius query`,
   `fix(ui): ...`, `test: ...`, `docs: ...`.
4. Open a PR into `main` as soon as something works (draft PRs are welcome). Fill in the template.
5. **CI must be green.** Get a 2-minute review from one other person, then squash-merge.
6. Rebase rather than merge when `main` moves: `git fetch && git rebase origin/main`.

## Rules that keep us out of each other's way

- **Stay in your files.** Each feature lists its files. The base pre-wired every API router
  (`whygraph/api/main.py`), UI tab (`ui/src/App.tsx`) and package, so you rarely need to touch shared files.
- **Contracts are shared.** These files define how the parts talk to each other:
  - `docs/schema.md` and `docs/events.md`
  - `whygraph/models/events.py` (the source of truth)
  - `ui/src/types/events.ts` (the TS mirror)

  If you change one, say so in the PR title (`[contract]`), update both mirrors, and tell the others.
- **All Cypher lives in the catalog** (`whygraph/graph/queries.py`). Agents, MCP tools and the UI run catalog
  queries only, and every query has a plain-English `explain`. Run `make docs` after changing it.
- **Stable string ids only.** Use `svc:checkout`, never FalkorDB internal ids (see `docs/schema.md`).
- **Dependencies:** adding one changes the lockfile.
  - Python: `uv add <pkg>`.
  - UI: `npm --prefix ui install <pkg>`.
  - On a lockfile conflict, take `main`'s version, then rerun the add command.
- **Secrets** go in `.env` only. Never commit keys.

## Local loop

```bash
make install   # once
make db        # FalkorDB + Browser (http://localhost:3000)
make smoke     # which FalkorDB features work on this server
make api       # :8000
make ui        # :5173 (Incident tab replays the Act 1 fixture — no agents or DB needed)
make test      # DB tests auto-skip if FalkorDB is down; CI runs them against a real FalkorDB
make lint
```

## AI assistants

We use AI coding assistants. You're still responsible for every line you merge, and you must be able to explain
the graph model, the queries and the design decisions to the judges. Don't merge code you haven't read.
