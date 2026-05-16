# Researcher Plugin — Roadmap

## v0.3.0 — Bug fixes & stability
- [x] Fix `formatRunStatus` only replacing first hyphen (use `split/join` + capitalize)
- [x] Skip 5-second polling when no runs are active
- [x] On plugin load, auto-revert orphaned "researching" items back to "To Research"
- [x] Add "Retry" action for failed runs (inline button on card)
- [x] Capitalize formatted run status strings

## v0.4.0 — Workflow flexibility
- [x] Right-click context menu on cards ("Open note", "Move to…", "Delete idea")
- [x] Move items backward via context menu (to-refine → backlog, to-research → to-refine)
- [x] Forward moves also accessible via context menu (not just drag-and-drop)
- [x] Delete/archive research ideas from sidebar with confirmation modal
- [x] "Mark as done" for in-progress items (skip research, close out idea)

## v0.5.0 — Sidebar search & filtering
- [ ] Search/filter bar to filter cards by title text
- [ ] Filter by vault tag
- [ ] Priority field (`research-priority: high/normal/low`) on research ideas
- [ ] Collapse group columns by clicking the header
- [ ] Active run count badge on ribbon icon

## v0.6.0 — Research note templates
- [ ] Custom question templates (vault note that defines default clarifying questions)
- [ ] Configurable note template for new research ideas
- [ ] "Research brief" auto-generation command (summary of answered questions, inserted before run)

## v0.7.0 — Notifications & run history
- [ ] Desktop notification (with "Open report" action) when a run completes
- [ ] Per-note run history panel (all past runs, not just the latest)
- [ ] "Delete completed runs older than X days" cleanup command
- [ ] "Open report" quick-action button on completed cards (no need to open note first)

## v0.8.0 — Sidecar improvements
- [ ] Expose sidecar search API (`RESEARCHER_SEARCH_API`) as a plugin setting
- [ ] Per-run engine selection (stub vs. open_deep_research) from the start modal
- [ ] Parse intermediate LangGraph output for real sub-step names in heartbeat
- [ ] Python environment validation on plugin load (warn if sidecar deps missing)

## v1.0.0 — Community release candidate
- [ ] Split `main.ts` into separate source modules (view, modals, settings, stores)
- [ ] Obsidian community plugin submission checklist (authorUrl, README, screenshots)
- [ ] Inline settings validation warnings (missing model, sidecar not found, etc.)
- [ ] Settings import/export (backup/restore configuration as JSON)
- [ ] In-sidebar help panel explaining the workflow for new users

## v1.1.0 — Iterative research
- [ ] Follow-up question generation after a report is completed
- [ ] "Re-run with additional context" command (pre-seeds new run with prior report)
- [ ] Research threads — group related ideas by tag in the sidebar

## v1.2.0 — Export & sharing
- [ ] Export report to HTML/PDF (standalone file for sharing outside Obsidian)
- [ ] Copy research brief to clipboard (formatted markdown)
- [ ] Publish to web app (export idea + report to companion Next.js kanban)

## v1.5.0 — Mobile / API-only mode
- [ ] API-only research mode (no subprocess — call a hosted endpoint directly)
- [ ] Remove `isDesktopOnly: true` (basic workflow works everywhere with API-only fallback)
- [ ] Tap-to-open action menus for mobile (replace drag-and-drop UX)

## v2.0.0 — Platform
- [ ] Plugin extension API (register custom research engines from third-party plugins)
- [ ] Research dashboard view (aggregate stats: ideas per stage, time per stage, run success rate)
- [ ] Scheduled research ("run every Monday and append a new report")
- [ ] Bidirectional web app + plugin sync
- [ ] Vault-wide research graph (which notes appear across research runs)
