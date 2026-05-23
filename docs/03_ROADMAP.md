# Roadmap

## Purpose

Sequence the work deferred in `02_COMPONENT_MAP.md` into phases. Each phase is "until done," not calendar-locked, but with a rough effort estimate. Phases are explicitly gated: the entry criteria for phase N+1 are non-negotiable, because skipping ahead is the single most common way research prototypes collapse under their own complexity.

The roadmap is shaped by one principle: **never start a phase before the previous one is delivering real daily value.** If v0.1 doesn't get used daily, v0.2 doesn't start.

## Phase summary

| Phase | Headline | Hardware | Rough effort |
|---|---|---|---|
| v0.1 | MVP: hybrid retrieval, deterministic citations, dumb surfacing | Mac | ~8 weeks |
| v0.2 | Agentic depth: orchestrator, memory, web, HITL graph | Mac | ~10 weeks |
| v0.3 | Autonomy: daemon, filing, contradiction detection, structural integrity | Mac | ~8 weeks |
| Phase 7 | GPU box: llama-swap, vLLM, heavyweight synthesis model | GPU box | ~3 weeks |
| Phase 8 | AI OS expansion: A2A, MCP, governance, AgentMesh | Both | ~12 weeks |
| Backlog | Research-grade: RecursiveMAS, GEPA+, latent compression | — | indefinite |

Detail per phase below.

---

## v0.1 — MVP

Covered in detail in `01_MVP_SCOPE.md`. Not repeated here.

**Exit criteria:** all five v0.1 success criteria from `01_MVP_SCOPE.md` met against the user's actual vault.

---

## v0.2 — Agentic depth

### Goal

Replace the flat single-turn research function with a real multi-step orchestrator, add cross-session memory, bring in live web sources, and ship the HITL visual graph UI that turns the orchestrator into something the user can steer.

### Entry criteria

- v0.1 exit criteria met.
- The user has been running v0.1 daily for at least two weeks without major regressions.
- The eval harness has been used to detect at least one regression caught before reaching the user (proving the harness works).

### Deliverables, in build order

1. **LangGraph orchestrator behind the existing `research()` interface.** No new capabilities — proves the swap is invisible to callers. Re-run the v0.1 eval suite; results should be within noise.
2. **ROMA decomposition pattern on top of LangGraph.** Atomizer, Planner, Executor, Aggregator wired as LangGraph nodes. Planner can spawn parallel Executors against the vault. The Composer/Corroborator/Critic pattern (v0.3) and the IterDRAG Chief-Editor/Researcher/Reviewer/Writer naming from the web-scraping report are aliases of the same shape — pick names per file, document in ADR-0010 successor when finalised.
3. **Mem0 memory layer.** Tri-signal retrieval, agent-mode init, persistent across sessions. Injected as context before the Planner runs.
4. **Web search adapter — SearXNG + DDGS.** Per ADR-0018. SearXNG when the user has Docker; DDGS as zero-infrastructure fallback. Single `search(query, k) -> list[SearchHit]` interface. *Must precede deliverable 5 (Crawl4AI fetch)* — you cannot fetch URLs you haven't found. The Planner's Researcher Executor first searches, then fetches.
5. **Crawl4AI web sub-agent (fetch) + `curl_cffi` fast path.** Exposed as an Executor type. *Must follow deliverable 3 (Mem0) and deliverable 4 (search)* — web-sourced facts land in memory with temporal metadata, so the memory layer must exist first; URLs must come from somewhere, hence search first. Planner can choose to delegate to web vs vault per sub-task. Two scrapers behind one `fetch(url) -> MarkdownDoc` interface: `curl_cffi` with Chrome JA3 impersonation for static/lightly-defended targets (cheap), Crawl4AI with `enable_stealth=True` for JS-rendered or moderately-defended pages. Selector heuristic: try `curl_cffi` first; fall back to Crawl4AI on 403/empty body. Web content lands in the main DuckDB index per ADR-0019; web-sourced claims carry `(url, anchor)` instead of `^id` in the citation render layer, but use the same `^id` shape as the DB primary key internally.
6. **HITL visual graph UI.** After the Planner produces its DAG, the plugin renders it as a node graph. User can prune branches, add URLs, expand nodes. Approved plan goes to execution.
7. **Terminal-style execution log.** Side panel streams orchestrator events (tool calls, sub-agent spawns).

Deferred to v0.2.x or "as needed" (not gated as v0.2 deliverables): Whoogle fallback, `nodriver` deep-CDP scraping, FlareSolverr Cloudflare-bypass proxy, Tor+Privoxy IP rotation. Built only when a real target forces the escalation — don't pay the operational cost for problems we haven't hit.

### Success criteria

- Eval suite shows agentic research is at least as accurate as v0.1 single-turn on simple queries, and measurably better on multi-source queries.
- Citation pass rate stays ≥95% with web sources included.
- User prunes the search graph at least 30% of the time, proving the HITL UI is load-bearing rather than ceremonial.
- Web search→fetch loop completes end-to-end against at least 3 distinct domain types (static HTML, JS-rendered SPA, lightly-protected commercial site) without manual intervention. If any of those three classes consistently fail, that's the trigger to escalate to `nodriver`/FlareSolverr; otherwise we ship without them.

### Risks

- LangGraph adds latency. Mitigation: measure end-to-end latency in the eval harness before and after; budget a hard ceiling (e.g. 30s for typical queries).
- Web sources introduce factual drift. Mitigation: temporal metadata on every web-sourced fact in Mem0; citation engine flags conflicting dated claims.

---

## v0.3 — Autonomy

### Goal

Move from "user invokes the system" to "the system acts on the vault on its own." This is the phase where the vision's autonomous-daemon pattern actually ships.

### Entry criteria

- v0.2 exit criteria met.
- At least 100 deep research queries run cumulatively without a citation regression escaping to the user.
- Mem0 store has grown organically (not by seeding) to enough volume that retrieval scoring is meaningful.

### Deliverables, in build order

1. **Autonomous daemon — expanded scope.** Extends the v0.1 ingestion file watcher (per ADR-0017) with filing, structural-integrity scans, and event-driven workflows. Same long-running process, broader responsibilities. Configurable watch directories. Health-monitored.
2. **Autonomous filing pipeline.** Daemon detects new notes in inbox folders, runs them through the orchestrator with a "categorise + link + file" plan, moves them into the vault. User reviews the *result*, not each step.
3. **Composer / Corroborator / Critic pattern.** Layered review at the orchestrator level (not just citation verification). Reduces fabrication on long-form output; required before contradictions can be detected reliably.
4. **Contradiction detection in surfacing.** When surfacing related notes, flag those that contradict the active note (using Corroborator-style review). This is what makes the surfacing capability "smart."
5. **Vault structural integrity sweep.** Periodic background job: orphan detection, broken link repair proposals, stale MOC drift detection. Reported as a digest, not auto-applied.
6. **(Optional) n8n for file-trigger flows.** If the bespoke daemon is brittle, replace it with n8n local-file-trigger workflows. Decision point, not a guaranteed deliverable.
7. **(Optional) Obsidian Canvas as agent workspace.** Agent reads/writes `.canvas` files for visual collaboration. Defer further if Canvas adoption is low in user workflow.

### Success criteria

- Inbox folder drains autonomously: median time-to-filed under 30 minutes, user override rate under 20%.
- Surfacing panel highlights at least one genuine contradiction per week of typical use.
- Structural integrity digest produces actionable repairs the user actually applies.

### Risks

- Autonomous edits to the wrong file class. Mitigation: hard convention enforcement — daemon writes only to allow-listed directories until trust is established.
- Notification fatigue from surfacing/integrity. Mitigation: digest pattern + per-feature mute, not per-event popups.

---

## Phase 7 — GPU box

### Goal

Migrate inference off the Mac onto a dedicated GPU machine to unblock larger synthesis models. The orchestrator, retrieval, citation, and UI layers do not change.

### Entry criteria

- GPU box physically present and reachable on local network.
- v0.3 (or at minimum v0.2) is the daily-driver version on the Mac.
- A hypothesis worth testing on the new hardware — "synthesis quality is limited by the Mac model" — backed by qualitative evidence from daily use.

### Deliverables

1. **vLLM running on the GPU box.** One model loaded initially. Verify throughput, latency, and accuracy against the eval suite.
2. **llama-swap deployed in front of vLLM.** OpenAI-compatible endpoint. Configured with at least two models (small executor, large synthesiser) and FIFO+TTL policies.
3. **Inference adapter URL flipped.** A single config change in `packages/inference`. No code changes elsewhere — that's the test that the adapter abstraction held.
4. **Mac fallback path retained.** When the GPU box is unreachable, the adapter falls back to local Ollama. Local-first principle preserved.
5. **GPU-box-specific configs.** FP8 KV cache, PagedAttention, prefix caching, MLA-enabled model selection — all in `infra/llama-swap` config, not in application code.

### Success criteria

- End-to-end eval suite runs against GPU box and shows measurable quality improvement on synthesis tasks; no regression on retrieval or citation.
- Inference adapter required zero code changes outside its own module.
- Mac fallback works when GPU box is down.

### Risks

- Network latency between Mac and GPU box dominates. Mitigation: measure first; if real, run orchestrator on the GPU box too.
- Model-swap thrashing under interactive load. Mitigation: tune TTL conservatively; route surfacing (low-latency, small model) and synthesis (high-quality, large model) to different proxy slots.

---

## Phase 8 — AI OS expansion

### Goal

Open the system up. Until now it has been a closed loop: one user, one plugin, one orchestrator. Phase 8 turns it into a node in a larger agentic mesh and adds the governance machinery to make that safe.

### Entry criteria

- At least one external use case clearly identified — e.g. a separate scheduling agent that needs read access to the vault, or an MCP client (Claude Desktop, Codex, etc.) the user wants to integrate.
- v0.3 stable on Mac, Phase 7 stable if applicable.
- Willingness to pay the maintenance cost of security infrastructure (key rotation, policy reviews) on an ongoing basis.

### Deliverables

1. **MCP server exposing vault retrieval as a tool.** Simplest external integration. Lets Claude Desktop, Codex, or any MCP client query the vault.
2. **A2A protocol implementation.** JSON-RPC over HTTPS, Agent Cards at `/.well-known/agent.json`, SSE streaming for long-running tasks.
3. **Vault Agent Card published.** The plugin hosts its own Agent Card describing capabilities, modalities, auth.
4. **AGT policy engine integrated.** Every tool call routed through the policy engine. Start with permissive policies, tighten over time.
5. **Policy-as-code library.** OPA Rego or Cedar policies for the common cases (read-only paths, time-windowed external calls, approval-required operations).
6. **AgentMesh identity layer.** Ed25519 keys per agent, IATP handshake, SPIFFE/SVID verification. Only meaningful once there are ≥2 agents exchanging messages.
7. **(Conditional) n8n Queue Mode.** Only if throughput demands it. Single-user load almost certainly doesn't.

### Success criteria

- At least one external agent (MCP or A2A client) successfully queries the vault with the user's approval gate engaged.
- Policy engine has blocked at least one unintended action in benchmark or red-team testing.
- Per ADR-0005 (as updated for Phase 8), this system makes no direct cloud LLM calls with vault content. Vault content reaching external MCP/A2A clients may transit cloud services depending on the *client's* configuration; the user accepts that scope as a deliberate trade for interoperability.

### Risks

- Scope explosion. Mitigation: each numbered deliverable is independently shippable; stop at any point where ROI drops.
- Security infrastructure rotting from disuse in a single-user system. Mitigation: only build the parts a real external use case demands.

---

## Backlog — research-grade work

These do not get a phase. They are revisited only when there is a clear hypothesis worth testing and a working system underneath worth optimising.

| Item | Source | When to revisit |
|---|---|---|
| GEPA+ prompt optimisation | OS §1.1 | Once v0.2 prompts have stabilised; run offline as `experiments/`. |
| Composer–Corroborator–Critic empirical validation (refusal behaviour) | OS §1.2 | After v0.3 ships the pattern; evaluate the emergent-refusal claim against the actual implementation. |
| RecursiveMAS / RecursiveLink latent thought compression | OS §4 | If multi-agent latency becomes a real bottleneck in Phase 8. Likely never on single-user hardware. |
| Dual-rate training of RecursiveLink modules | OS §4.2 | Same. |
| AI-BOM provenance tracking | OS §6.1 | When dependencies stabilise enough that a manifest stops thrashing. |
| HashiCorp Vault for secrets | OS §5.2 | When the project leaves single-machine deployment. Probably never. |
| Cross-model verification kernel | OS §6.1 | When there are multiple model providers worth cross-checking. |

---

## How to use this document

When starting work, the only valid question is: *am I still on the current phase, or have I drifted into the next one?* Drift is the failure mode. If a v0.1 task starts requiring LangGraph, that's a signal v0.1 scope has expanded — push back to the doc, not into the code.

When closing a phase, the entry criteria for the next phase are the gate. If they aren't met, the phase ships and the next phase waits, even if the next deliverable feels exciting.
