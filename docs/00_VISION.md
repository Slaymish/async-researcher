# Vision

## What this is

A local-first AI system that turns the Obsidian vault from a passive store of notes into an active collaborator. It runs entirely on local hardware, never sends vault contents to external APIs, and is grounded by the architectural patterns described in `ArchitectureSpecification.md` and `LocalAgenticRAGArch.md`.

This document captures what the system does *for the user*. Technical scope lives in `01_MVP_SCOPE.md`; technical decisions live in `05_DECISIONS.md`.

## Who it's for

A single user (Hamish) whose vault is dominated by two kinds of content:

- **Active work** — project plans, code snippets, ADRs, build artefacts.
- **Reference material** — academic papers, technical specs, dense notes.

Two pain points drive the project:

1. **Fleeting capture outpaces organisation.** Raw notes accumulate faster than they get filed, tagged, or linked. The vault is rich but increasingly entropic.
2. **Active project notes bleed into reference material.** The boundary between "what I'm working on now" and "what I've learned" is porous, and retrieval suffers.

## The two headline capabilities

The system stands on two equally important pillars. Either alone would justify the project; together they define it.

### 1. The vault talks back unprompted

When the user is working on something, the system proactively surfaces related notes, contradictions with prior thinking, stale ideas worth revisiting, and connections the user wouldn't have made manually. Triggered by user activity — opening a file, editing a note, starting a project — not by explicit queries.

### 2. Deep research on demand, grounded to the vault

The user asks a complex question. The system runs a hierarchical "Wide-to-Deep" research flow: a planner agent maps the conceptual landscape across the vault, persistent memory, and (once v0.2 brings live web sources online) external sources; execution agents drill into the most relevant branches; a synthesis agent produces a long-form report where **every claim is grounded to a specific `^id` block** in the vault, and — once external sources land — to verifiable external citations as well. Citations are deterministic, not hallucinated. v0.1 is vault-only.

These two capabilities share most of their substrate — the same graph index, the same retrieval layer, the same citation engine, the same orchestrator — which is why both can be first-class in v0.1 without doubling the build.

## What the system does, in order of importance

1. **Surfaces proactively.** As the user edits a note, opens a file, or works on a project, the system pushes relevant context into a side panel — related notes, contradictory claims from older notes, forgotten threads on the same topic.
2. **Runs deep research with verifiable citations.** Long-form synthesis across vault + memory + web, every claim mapped to an `^id` block, zero hallucinated references.
3. **Files fleeting notes autonomously.** New notes dropped into an inbox are categorised, tagged, linked, and moved to the right place in the vault without user intervention. The user reviews outcomes, not every decision.
4. **Maintains the vault's structural integrity.** Detects orphaned notes, broken links, drifted Maps of Content, and proposes repairs.

## Non-negotiable boundaries

- **No vault contents leave the machine.** All inference is local. Cloud LLM APIs are excluded, even for synthesis, even when faster. This is a sovereignty project before it is a capability project.
- **The user owns existing notes.** The system may freely create new notes, build indexes, write summaries, and propose edits — but modifications to user-authored content are surfaced for review unless the user has explicitly delegated that file class.

Within those bounds: maximise autonomy. Background runs are fine, auto-organisation of new content is fine, the system should act without asking permission for every step.

## What this is not

- Not a chatbot. The primary interface is the vault itself, not a chat window.
- Not a productivity tool with AI bolted on. AI is the substrate; the tool is the vault.
- Not a SaaS product. Single user, single machine, no multi-tenancy concerns.
- Not a faithful reimplementation of either spec document. The specs are the north star; the build is whatever fraction of them delivers the four capabilities above.

## Success criteria

These describe the **eventual state of the mature system** across all roadmap phases, not v0.1 specifically. Per-phase criteria live in `01_MVP_SCOPE.md` and `03_ROADMAP.md`. The project is working if, after a month of daily use of the mature system:

- The proactive surfacing panel is part of the user's daily working environment — open most working days, useful most working days, surfacing at least one genuinely forgotten note per week.
- The user runs at least one deep research query per week and trusts the resulting report enough not to re-verify citations manually.
- The fleeting-notes inbox stays at or near zero without manual filing effort. *(Requires v0.3 autonomous filing — not testable until then.)*
- The user prefers reaching for this system over any cloud AI tool for vault-adjacent work.

The project has failed if, after a month of using the mature system, the user has to manually re-organise the inbox, distrusts the citations, finds the proactive surfacing noisy enough to disable, or reverts to a cloud LLM for deep research because the local version is too slow or shallow.
