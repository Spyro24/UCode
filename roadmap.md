# UCode — Roadmap

**Status:** Draft 0.2 · **Last updated:** 2026-11-14

## 1. Vision

UCode is a code editor where the unit of work is not a buffer of text but a **node**. Every file is a
node on a canvas, and every node exposes typed **inputs** and **outputs**. Code that used to be
connected by `import`, `#include` and orchestration scripts becomes a visible, inspectable, executable
graph.

The long-term goal is an editor for projects whose shape is obvious at a glance: you see what feeds
what, you can type-check the wiring, you can run any subtree, and you can rewrite a node's contract
without grepping for callers.

Two directions must both be served, and they must not fight each other:

1. **A real editor.** Text is still where code is written. UCode wraps a first-class native text
   editing experience (syntax, LSP, multi-cursor, search, git) and never forces the graph on someone
   who wants to write a single file.
2. **A real graph.** The graph is not a decoration of the file tree. Edges are the dependency truth,
   ports are a type-checked contract, and the runtime can execute the graph.

## 2. Hard constraints

These are settled and shape everything below. They are not re-litigated per milestone.

| # | Constraint | Consequence |
| --- | --- | --- |
| C1 | **Python and C are the only supported languages in v1.** | Port inference needs exactly two front-ends; the value model must bridge a dynamic and a static language. No TypeScript/JavaScript anywhere in the product. |
| C2 | **No web technology in the UI.** No Electron/Tauri/WebView, no HTML, CSS, JavaScript, Web Components, React or canvas-in-a-browser. | Native toolkit for all widgets; a native text editor control; native file dialogs; the renderer is a platform drawing API. |
| C3 | **The canvas is tile-based; default tile is 48 px.** | Layout, ports, hit-testing, snapping, routing and the spatial index are all quantised to the tile grid, in integer tile coordinates. |
| C4 | Plain text on disk is the source of truth. | No database, no proprietary project format. A project must survive `git clone` and outlive UCode. |
| C5 | **The application is written in Python.** C is only an optional accelerator for hot paths. | Python is the reference implementation of every feature; the editor must run with the C extension absent. No feature may require C. |

## 3. Core concept

A **node** is a file. Its **ports** are its public contract.

| Concept | Meaning |
| --- | --- |
| `Node` | A file — or, later, a group of files collapsed into one node. |
| `InputPort` | A named, typed dependency the node requires. |
| `OutputPort` | A named, typed value the node produces. |
| `Edge` | A directed connection from an `OutputPort` to a compatible `InputPort`. |
| `Graph` | The set of nodes and edges — a project, a folder, or a subgraph. |
| `Run` | An evaluation of a subgraph in dependency order, with memoised results. |

A minimal Python node, source-first:

```python
# /// ucode: node
# /// in   items: list[Item]
# /// in   weights: dict[str, float] = {}
# /// out  top: list[Item]
# /// out  mean: float
def score(items, weights={}):
    ...
```

A minimal C node:

```c
// /// ucode: node
// /// in   n: i64
// /// out  result: f64
double mean_of_squares(long n);   /* port `n` → out `result` */
```

The annotation block is the contract. It is parsed by the core, validated against the implementation,
and is the only thing the graph needs in order to render and type-check a node it has never opened.

**Why annotations rather than a sidecar schema:** the source file stays the source of truth, diffs
stay readable, `git blame` stays meaningful, and the editor degrades gracefully in `vim`. Everything
that is *not* code — tile positions, colours, collapsed state — lives under `.ucode/`.

## 4. Tiles

The tile is the atomic unit of the canvas, and it is the reason layout can be exact instead of
hopeful.

| Property | Default | Notes |
| --- | --- | --- |
| Tile edge | **48 logical px** | Project setting, any multiple of 8 from 32 to 128. Stored in `.ucode/settings.json`. |
| Node grid | integer tiles | A node is `w × h` tiles, minimum `2 × 2`. Never a pixel rectangle. |
| Port pitch | 1 tile | Input ports stack down the left edge, one per tile row; outputs down the right edge. |
| Text grid | ¼ tile | Monospace cell = 12 px at a 48 px tile; 4 lines per tile; node header occupies exactly 1 tile row. |
| Edge routing | orthogonal, on tile boundaries | Channel routing with lane offsets in ¼-tile steps; ¼-tile corner radii. |
| Snapping | always on, in tile space | There is no free-floating mode, so no "nearly aligned" states to clean up. |
| Zoom | scale of tile space | Tile stays 48 logical px; device pixels = `tile × dpr × zoom`. |

Consequences that are load-bearing:

- **Positions are integers.** `layout.json` stores `{"tile": [7, 3], "size": [6, 4]}` — merge conflicts
  become trivial per-node keys, CRDT ops are integer assignments, and undo is a diff of small numbers.
- **The tile grid is the spatial index.** A sparse hash of occupied tiles gives O(1) hit-testing and
  culling without a broad-phase structure, because nothing is ever off-grid.
- **Tile-aligned ports make connection affordances unambiguous.** You drag to a slot, not to a pixel;
  compatible slots highlight, occupied slots reject.
- **Rendering is resolution-independent by construction.** High-DPI is a scale change, not a layout change.

**Assumption:** "tiles" here are the canvas/layout unit — the grid nodes, ports and edges live on, not a
character-cell code view. If tiles are meant to hold content themselves, §4 is the section to revise.

## 5. Design principles

1. **Plain text on disk wins.** A project opened in UCode and committed with `git` must be
   reviewable, and must still work after UCode is uninstalled.
2. **The graph is derived, then authored.** Ports start as inferred from real code (signatures,
   headers, call sites). Authors pin them to declared contracts when they want stability.
3. **Every edge is checkable.** Type mismatches are errors, not warnings. Cycle detection is instant.
   An invalid graph stays editable but never runs silently.
4. **No wall-clock surprise.** Running a node runs exactly what the graph says it depends on.
5. **Latency is a feature.** Pan, zoom and node-drag at 60 fps on a 5 000-node graph. Keystroke to
   paint under 16 ms. Anything slower is a bug.
6. **Local-first.** Files, runs and history work offline. Collaboration layers on top; it is never
   required to open a project.
7. **Composable core.** The graph model, type checker and scheduler live in `ucode.core` with no Qt
   dependency, so the desktop app, the CLI and CI all use the same engine.

## 6. Domain model

```
Project
├── files/            source files (nodes): *.py, *.c, *.h
├── .ucode/
│   ├── layout.json   tile positions, sizes, viewport, groups
│   ├── settings.json tile size, language profiles, run presets
│   └── cache/        parse, compile and type caches (gitignored)
└── graph.json        optional explicit edges + pinned ports
```

```jsonc
// graph.json — only what cannot be derived from source
{
  "version": 1,
  "edges": [
    { "from": "src/score.py#top", "to": "src/render.py#items" },
    { "from": "src/parse.c#words", "to": "src/score.py#items" }
  ],
  "pinned": { "src/score.py": { "in": ["items", "weights"] } }
}
```

```jsonc
// .ucode/layout.json — integers, tile units
{
  "version": 1,
  "tile": 48,
  "nodes": {
    "src/score.py":  { "tile": [7, 3], "size": [6, 4], "collapsed": false },
    "src/render.py": { "tile": [16, 3], "size": [5, 5] }
  }
}
```

Node identity is the path relative to the project root, so renaming a file is a node rename and
`git mv` keeps history. Edges referencing a deleted path become *dangling* and are surfaced as
repairable errors rather than dropped.

### Cross-language type lattice

Because Python and C must share ports, port types map onto one small lattice, not onto either
language's type system:

```
bool · i64 · f64 · string · bytes · list<T> · map<string,T> · record{…} · handle<opaque>
```

Python's `list[Item]` and C's `Item *` (plus length) both resolve to `list<record>`; anything that
cannot be expressed — a C `FILE*`, a Python file object — becomes `handle<opaque>`, which is
connectable only to the same handle type and is not serialisable. This lattice is what makes an edge
between a `.c` and a `.py` node checkable, and what lets a run be recorded and replayed.

## 7. Architecture

Everything is Python. C appears in exactly one place: an optional accelerator for hot paths. The editor
runs completely without it, and no feature may depend on it.

```
src/ucode/                    Python package — the whole application
├── ui/         window, tile canvas, text editor, panels, dialogs     (M2)
├── core/       graph model, ports, tile math, validation, scheduler  (M1)
├── languages/  Python `ast` front-end · C front-end via libclang     (M3)
├── runtime/    node drivers, capabilities, value encoding            (M4)
├── cli/        `ucode check` / `ucode run`                           (M7)
└── accel/      optional C extension: same API, faster                (post-M5)
```

Rules for the accelerator:

- **Every accelerated function keeps a pure-Python implementation.** `accel.load()` returns the
  compiled version when it is built, the Python one otherwise. The extension is never required.
- **It is added only after a measurement** shows Python is the bottleneck, and it implements the same
  algorithm — never a smarter one. Premature C is a second codebase with its own bugs.
- **Both implementations run the same property tests**, so drift fails CI instead of shipping.
- First candidates, in order: tile visibility culling (per frame), edge routing, value encode/decode,
  annotation parsing.

Toolkit: **Qt via PySide6** — native widgets drawn by a platform toolkit, no browser engine, real text
widgets, native dialogs, high-DPI and accessibility, and a paint API fast enough for a 48 px tile grid.
**SDL3 + a hand-rolled immediate-mode UI** remains the challenger and wins only if Qt's painting cannot
hold the frame budget (Spike A).

## 8. Language specifics

**Python** — inference from `ast`: module-level `__all__`, public function signatures, type hints,
dataclasses, and `TypedDict`s. Execution in a child process started with `-I` (isolated) so no user
`sitecustomize` or `PYTHONPATH` leaks in. Diagnostics via `pylsp`/`pyright` (either is a plain LSP
client; no web runtime involved).

**C** — a translation unit is a node, and its **header is its port contract**: every non-static
function declaration becomes ports, with `struct`/`typedef` mapped into the lattice. `#include`
edges are derived and shown as a separate edge class from call-graph edges, because "this file is
textually included" is not the same claim as "this function consumes that value". Diagnostics via
`clangd`; parsing via libclang where available with a fallback to a lightweight declaration scanner
so that C works even without LLVM installed.

**Interop** — a Python node can consume a C node's output and vice versa, because neither passes a
native object across the boundary: values are encoded with the core's tagged binary format. That same
boundary makes memoisation, replay and the value inspector fall out for free.

## 9. Milestones

Milestones are sequential but overlap by one: design for M*n+1* starts while M*n* is in review. Each
milestone ends with a demo on a real repository, not a synthetic one.

### M0 — Foundations and de-risking · *~2 weeks*

Prove the risky parts before committing the architecture.

- [ ] Write `SPEC.md`: node/port/edge semantics, annotation grammar for both languages, the type
      lattice, resolution rules, error taxonomy, `.ucode` format v1.
- [ ] Spike A: tile renderer — Qt custom paint vs SDL3, 5 000 nodes at 48 px tiles. Measure frame time
      at zoom 0.25/1.0/2.0 and on a HiDPI display.
- [ ] Spike B: native text editor — QScintilla vs a `QPlainTextEdit` + custom highlighter. (CodeMirror
      and Monaco are excluded by C2, so this is now a genuinely load-bearing choice.)
- [ ] Spike C: inference — libclang presence/portability for C, `ast` for Python, on a real repo.
- [ ] Spike D: execution — Python subprocess latency; `cc -shared -fPIC -O2` compile latency and
      warm dlopen latency; where the compile cache must live.
- [ ] Decide: toolkit, text control, C front-end strategy, the accelerator boundary, and the value
      encoding's first version.
- [ ] Repo scaffolding: a plain `src/ucode` tree started by the system interpreter through
      `run.py` — no packaging, no virtualenv — plus `pytest`, and `src/ucode/accel/` present but
      deliberately unbuilt.

**Exit:** one decision record per spike, `SPEC.md` reviewed.

### M1 — Core model · *~3 weeks*

The model exists in pure Python, is tested headlessly, and is the only thing the UI talks to.

- [ ] `ucode.core`: `Project → Graph → Node → Port → Edge` as dataclasses; **no Qt import anywhere
      under `ucode.core`.**
- [ ] Annotation parser for both `# ///` (Python) and `// ///` (C) block grammars; tolerant of malformed
      input, reporting precise line numbers.
- [ ] Type lattice with unification; cross-language edge checking (`.c#out` → `.py#in`).
- [ ] Validation: missing required input, duplicate port, type mismatch, dangling edge, cycle (report
      the full cycle path, not just "cycle found").
- [ ] Tile math: quantisation, occupancy map, reserved-slot checks, ¼-tile routing with obstacle
      avoidance and lane offsets.
- [ ] `ucode.accel`: loader that prefers the compiled extension and falls back silently to the Python
      implementation, with one shared property suite run against whichever variant is loaded.
- [ ] Tests: `pytest` only — property tests for cycle detection, topo sort and routing (no edge crosses
      a node, no two edges overlap on the same lane).

**Exit:** `ucode graph ./some-project --check` prints a valid graph, exits non-zero on errors, and
imports a real mixed Python/C repo without crashing.

### M2 — Editor MVP: see and wire the project · *~4 weeks*

First usable build. Someone can open a project, see every file as a tile-aligned node, and connect them.

- [ ] Native shell: project picker, recent projects, file watching, native dialogs, settings.
- [ ] Canvas: pan, zoom, selection, box-select, drag-and-snap in tile space, layout persisted to
      `.ucode/layout.json`.
- [ ] Node rendering on the tile grid: header row, port slots on 1-tile pitch, type labels, status
      badge, collapsed 1-tile-tall summary.
- [ ] Edge authoring: drag output → input slot, compatibility highlighting, rejected slots shown as
      such, ¼-tile orthogonal routing.
- [ ] Native text editor pane on a node, editing the real file; syntax highlighting for both languages.
- [ ] Create / delete / rename nodes (rename uses `git mv` when the project is a git repo).
- [ ] Command palette with fuzzy search over nodes and files.
- [ ] Diagnostics: list, per-node badge, click-to-navigate.
- [ ] Atomic autosave; external-change reconciliation prompt.

**Exit:** open a mid-size real project, lay it out, wire three files, edit one, and have everything
survive restart and `git commit`. Frame time stays inside budget at 1 000 nodes.

### M3 — Intelligence: the editor understands the code · *~4 weeks*

The graph stops being a hand-maintained picture and becomes a computed view.

- [ ] Python inference via `ast`; C inference via libclang (with the fallback scanner).
- [ ] LSP client for `clangd` and `pylsp`/`pyright`; diagnostics into node badges, hover types on ports.
- [ ] `#include` edges vs call-graph edges: derived, visually distinct, independently toggleable.
- [ ] "Why is this connected?" — path highlighting between any two nodes.
- [ ] Unused-output and orphan detection; drift detection between edges and real imports/includes.
- [ ] Import/export sync policy: decide and implement whether an edge implies an `import`/`#include`,
      and keep edges and code from drifting. **This is the crux of the product — write it down first.**
- [ ] Rename a port → project-wide preview and apply (Python call sites, C prototypes).
- [ ] Incremental re-parse on keystroke; caches keyed by content hash.

**Exit:** a 500-file mixed project cold-opens in under 5 s; editing a file updates its node's ports
without manual refresh; renaming a port updates every consumer.

### M4 — Execution: run the graph · *~6 weeks*

Nodes are not just pictures. Any subgraph can run.

- [ ] Scheduler: topological execution, per-node memoisation keyed by input hash, cancellation, timeouts,
      streaming output, deterministic ordering.
- [ ] Value encoding v1: tagged binary encode/decode in Python; fuzz the round-trip with `hypothesis`.
      Accelerate in C only if profiling says it matters.
- [ ] Python driver: isolated child process, no ambient `PYTHONPATH`, no network unless granted.
- [ ] C driver: harness generation, `cc -shared` into a content-addressed `.so`, `dlopen` in a runner,
      compile cache with toolchain-flags key in the hash, clear errors for missing headers/flags.
- [ ] Capabilities per node or per project profile: fs roots, network, env allowlist; denied by default.
- [ ] Run log: per-node timing, output, error mapped back to source line.
- [ ] Value inspector: view a port's value as a tree; pin a literal as an input override.
- [ ] Literal nodes (string, number, JSON, secret reference) usable as inputs.
- [ ] Watch mode: re-run the affected subtree on save, debounced.
- [ ] Secrets in the OS keychain; never in project files, never in the run log.

**Exit:** a mixed project (C parser → Python transform → file write) runs entirely from the canvas,
shows per-node timings, re-runs only the affected subtree on edit, and refuses a denied capability
with a comprehensible error.

### M5 — Scale and ergonomics · *~4 weeks*

- [ ] Tile-space culling and LOD: far zoom = solid tile blocks with type colour, mid = ports only,
      near = text. Nothing paints off-screen.
- [ ] Auto-layout on the tile grid (layered/Sugiyama, then quantised) as a one-shot command and a
      live "tidy" mode.
- [ ] Dragging never triggers a world re-layout; routing is incremental.
- [ ] Collapse a selection into a subgraph node with derived ports; expand back.
- [ ] Multi-cursor, multi-node editing; graph undo/redo with grouped ops (integer diffs, cheap).
- [ ] Global search across text, port names and types; jump-to-port.
- [ ] Minimap, breadcrumbs, and keyboard-only access to every canvas action.
- [ ] Theming (light/dark/high-contrast) and full keyboard accessibility for the canvas surface.
- [ ] Performance budget enforced in CI: 5 000 nodes, < 16 ms frame, < 5 s cold open, HiDPI included.

**Exit:** budgets green on both a 5 000-node synthetic graph and a real 500-file project; a
keyboard-only user can open, wire and run a graph.

### M6 — Collaboration and history · *~6 weeks*

- [ ] CRDT document model in `ucode.core` for graph and tile layout; edge/text sync via the same op log.
      (No JavaScript CRDT libraries — this is ours, and integers make it tractable.)
- [ ] Presence: live cursors, selections, per-node "who is here".
- [ ] Local history: snapshot per save; time-travel scrub for a single node.
- [ ] Graph diff view between any two commits: added/removed nodes and edges.
- [ ] Sync protocol + a reference server in Python; self-hostable, never required.
- [ ] Conflict policy: `layout.json` merges per node key, never whole-file.

**Exit:** two clients, offline edits, reconnect, no lost edges; graph diff is readable on a real PR.

### M7 — Extensibility · *~5 weeks*

- [ ] Plugin API: Python plugins (custom node types with declared ports, renderers, drivers). No C
      plugin ABI in v1.
- [ ] Plugin permission manifest in the core; no plugin gets ambient fs/network by default.
- [ ] Template gallery: new project from a graph template.
- [ ] CLI/CI: `ucode run <node>`, `ucode check`, a CI recipe that validates graph integrity.
- [ ] Importers: turn an existing repo's imports/includes into edges in one command; export to
      Mermaid/Graphviz for docs.
- [ ] Spec versioning policy and compatibility guarantees.

**Exit:** a plugin written in a separate package using only public API adds a node type end-to-end;
CI validation runs on a real repo.

### M8 — Hardening and v1.0 · *~4 weeks*

- [ ] Crash resilience: autosave journal, restore-on-launch, corrupt-cache self-heal, `.so` cache GC.
- [ ] Security review: capability escapes, path traversal via node ids, secret leakage into run logs,
      plugin permissions, unsafe `dlopen` of stale artifacts.
- [ ] Accessibility audit; internationalisation scaffolding.
- [ ] Docs: user guide, spec, plugin guide, format migration guide.
- [ ] Packaging: AppImage + `.deb`, macOS `.dmg` (signed/notarised), Windows `.msi`; auto-update channel.
      Bundled Python runtime or documented system requirement — decide here, not at release.
- [ ] Opt-in, aggregate-only telemetry, documented.

**Exit:** v1.0 tagged, installable on all three platforms, docs complete, no open P0/P1 issues.

## 10. Cross-cutting workstreams

| Workstream | Runs from | Notes |
| --- | --- | --- |
| Performance budgets in CI | M1 | Bench harness on synthetic + real projects; regressions block merge. |
| Testing | M1 | `pytest` across the package, golden files for the parser, `hypothesis` fuzzing on the parser and value encoding, accelerator parity tests, a few UI smoke tests only. |
| Spec discipline | M0 | Any format change needs a `SPEC.md` diff and a migration entry. |
| Accessibility | M2 | Keyboard paths from day one, not retrofitted in M8. |
| Security | M4 | Capabilities and secret handling are design inputs, not an end review. |

## 11. Non-goals for v1

- Any web technology in the UI: no Electron, Tauri, WebView, HTML, CSS, JavaScript, Web Components.
  Hard constraint C2.
- TypeScript/JavaScript/other language support. Python and C are it until v1 ships.
- Replacing `git` — UCode reads and writes working trees; it does not become a forge.
- A general visual programming language. Nodes wrap real code; there is no separate node DSL whose
  semantics diverge from the code it represents.
- Mobile or tablet editing.
- Hosted multi-tenant sync as a paid product.
- Arbitrary pixel-precise layout. Everything snaps to tiles; that is the point.

## 12. Open decisions

| # | Question | Owner | Needed by |
| --- | --- | --- | --- |
| D1 | Do edges imply `import`/`#include`, or merely mirror them? | architecture | M3 start |
| D2 | Toolkit: Qt/PySide6 or SDL3 immediate mode? | architecture | M0 end |
| D3 | Are tiles purely layout, or do they hold content? | product | M0 end |
| D4 | Ports inferred from signatures only, or from a declaration checked against them? | architecture | M1 start |
| D5 | Is a C node a translation unit (`.c`) or a header (`.h`)? | architecture | M1 start |
| D6 | Bundled Python runtime, or system Python with a version floor? | packaging | M8 start |
| D7 | Subgraph node = folder on disk, or virtual grouping in `graph.json`? | architecture | M5 start |
| D8 | Licence (Apache-2.0 or MIT for adoption) | product | M2 end |
| D9 | Which hot path gets a C accelerator first, and what measurement justifies it? | performance | M5 start |

## 13. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Building a text editor from scratch (C2 removes CodeMirror/Monaco) | Months of undifferentiated work | Spike B in M0; bind Scintilla rather than write one unless it fails |
| Optional C accelerator drifts from the Python reference | Two behaviours, silent wrongness | One shared property suite run against both variants in CI; the accelerator never adds features |
| Two languages, two front-ends, one type lattice | Inference bugs erode trust | Start with exported signatures and header declarations only; show confidence; let users pin |
| C compile latency makes runs feel slow | Watch mode unusable | Content-addressed `.so` cache, warm dlopen, measure in Spike D, budget in M4 |
| Edges drift from real imports/includes | Graph becomes a stale diagram | M3 sync policy as a hard requirement with drift tests |
| Tile grid feels restrictive to users | Complaints, requests for pixel mode | Tile sizes are configurable; ¼-tile port slots and lane offsets give fine control without pixel freedom |
| Sandboxed execution and `dlopen` are a security footgun | Data loss, leaked secrets | Capability model in M4, keychain secrets, security review in M8 |
| Scope: editor + runtime + collab is three products | Nothing ships | Strict milestone exits; collab (M6) explicitly deferred past a usable v0 |
| Format churn | Trust loss | Versioned format and migrations from the first release |

## 14. Success metrics

| Phase | Metric | Target |
| --- | --- | --- |
| M2 | Cold open, 500 files | < 5 s |
| M2 | Frame time, 1 000 nodes @ 48 px tiles | < 16 ms |
| M3 | Port inference precision on real repos | > 95 % |
| M3 | Incremental re-parse after a keystroke | < 30 ms |
| M4 | Warm run latency, cached `.so` | < 100 ms |
| M4 | C compile cache hit rate in watch mode | > 90 % |
| M5 | Frame time, 5 000 nodes, HiDPI | < 16 ms |
| M5 | Keyboard-only task completion (open → wire → run) | 100 % |
| v1.0 | Crash-free sessions | > 99.5 % |

## 15. Immediate next steps

1. Draft `SPEC.md` — node/port/edge semantics, the annotation grammar for both languages, and the
   cross-language type lattice. Everything else is delivery.
2. Run Spike A (tile renderer) and Spike B (native text control) in parallel; both are cheap and both
   are load-bearing now that the web stack is off the table.
3. Scaffold the package: `pyproject.toml`, src layout, `pytest`, one `ucode` entry point, with
   `src/ucode/accel/` present but unbuilt.
4. Bring one real mixed Python/C repository in as the M2 acceptance target and keep using it in every
   milestone demo.
