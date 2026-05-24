// Research status sidebar — live progress during a deep research run.
// Opens automatically when research starts; updated via public methods from main.ts.
import { ItemView, WorkspaceLeaf } from "obsidian";
import type AiOsPlugin from "../main";

export const VIEW_TYPE_RESEARCH = "ai-os-research-status";

interface FetchStatus {
  url: string;
  title: string;
  status: "pending" | "fetching" | "done";
  chunks?: number;
}

export interface SubQueryState {
  text: string;
  target: "vault" | "web";
  rationale: string;
  status: "pending" | "searching" | "done";
  chunkCount?: number;
  fetches: FetchStatus[];
}

type Phase =
  | "idle"
  | "analyzing"
  | "planning"
  | "researching"
  | "verifying"
  | "assembling"
  | "done"
  | "error";

// Steps shown in the timeline (excludes "done" and "error" — handled separately)
const PHASE_STEPS: Phase[] = [
  "analyzing",
  "planning",
  "researching",
  "verifying",
  "assembling",
];

const PHASE_LABELS: Record<Phase, string> = {
  idle: "Idle",
  analyzing: "Analyzing question",
  planning: "Planning sub-questions",
  researching: "Researching",
  verifying: "Verifying citations",
  assembling: "Assembling report",
  done: "Done",
  error: "Error",
};

export class ResearchStatusView extends ItemView {
  private query = "";
  private phase: Phase = "idle";
  private subQueries: SubQueryState[] = [];
  private progressMessage = "";
  private errorMessage = "";

  constructor(
    leaf: WorkspaceLeaf,
    private readonly plugin: AiOsPlugin,
  ) {
    super(leaf);
  }

  getViewType(): string {
    return VIEW_TYPE_RESEARCH;
  }

  getDisplayText(): string {
    return "Research Status";
  }

  getIcon(): string {
    return "search";
  }

  async onOpen(): Promise<void> {
    this.render();
  }

  async onClose(): Promise<void> {
    this.plugin.onResearchSidebarClose();
  }

  // ── Public update API ────────────────────────────────────────────────────

  startResearch(query: string): void {
    this.query = query;
    this.phase = "analyzing";
    this.subQueries = [];
    this.progressMessage = "";
    this.errorMessage = "";
    this.render();
  }

  onPlan(
    subQueries: Array<{ text: string; target: "vault" | "web"; rationale: string }>,
  ): void {
    this.phase = "researching";
    this.subQueries = subQueries.map((sq) => ({
      ...sq,
      status: "pending" as const,
      fetches: [],
    }));
    this.render();
  }

  onWebSearch(
    subQuery: string,
    hits: Array<{ url: string; title: string }>,
  ): void {
    const sq = this.subQueries.find((s) => s.text === subQuery);
    if (sq) {
      sq.status = "searching";
      sq.fetches = hits.map((h) => ({ url: h.url, title: h.title, status: "pending" as const }));
      this.render();
    }
  }

  onWebFetch(subQuery: string, url: string, title: string): void {
    const sq = this.subQueries.find((s) => s.text === subQuery);
    if (!sq) return;
    const f = sq.fetches.find((x) => x.url === url);
    if (f) {
      f.status = "fetching";
    } else {
      sq.fetches.push({ url, title, status: "fetching" });
    }
    this.render();
  }

  onWebFetchDone(subQuery: string, url: string, chunks: number): void {
    const sq = this.subQueries.find((s) => s.text === subQuery);
    if (!sq) return;
    const f = sq.fetches.find((x) => x.url === url);
    if (f) {
      f.status = "done";
      f.chunks = chunks;
    }
    this.render();
  }

  onExecutorDone(subQuery: string, _target: string, chunkCount: number): void {
    const sq = this.subQueries.find((s) => s.text === subQuery);
    if (sq) {
      sq.status = "done";
      sq.chunkCount = chunkCount;
      this.render();
    }
  }

  onProgress(message: string): void {
    this.progressMessage = message;
    // Advance phase from progress message prefix
    if (message.startsWith("Analyzing")) this.phase = "analyzing";
    else if (message.startsWith("Planning") || message.startsWith("Recalled"))
      this.phase = "planning";
    else if (message.startsWith("Researching") || message.startsWith("Combining"))
      this.phase = "researching";
    else if (message.startsWith("Verifying") || message.startsWith("Correcting"))
      this.phase = "verifying";
    else if (message.startsWith("Assembling") || message.startsWith("Saved"))
      this.phase = "assembling";
    this.render();
  }

  onDone(): void {
    this.phase = "done";
    this.progressMessage = "";
    this.render();
  }

  onError(message: string): void {
    this.phase = "error";
    this.errorMessage = message;
    this.render();
  }

  // ── Render ───────────────────────────────────────────────────────────────

  private render(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("ai-os-research-sidebar");

    if (this.phase === "idle") {
      const emptyEl = contentEl.createDiv({ cls: "ai-os-rs__empty" });
      emptyEl.createDiv({
        cls: "ai-os-rs__empty-text",
        text: "Start a research query to see live progress here.",
      });
      const btn = emptyEl.createEl("button", {
        cls: "ai-os-rs__new-research-btn mod-cta",
        text: "New research…",
      });
      btn.addEventListener("click", () => {
        this.plugin.openResearchModal();
      });
      return;
    }

    // Query header
    const header = contentEl.createDiv({ cls: "ai-os-rs__header" });
    header.createDiv({ cls: "ai-os-rs__section-label", text: "Question" });
    header.createDiv({
      cls: "ai-os-rs__query",
      text:
        this.query.length > 200 ? this.query.slice(0, 199) + "…" : this.query,
    });

    // Phase timeline
    const steps = contentEl.createDiv({ cls: "ai-os-rs__steps" });
    for (const phase of PHASE_STEPS) {
      this.renderStep(steps, phase);
    }

    // Sub-query cards (populated after planning)
    if (this.subQueries.length > 0) {
      const list = contentEl.createDiv({ cls: "ai-os-rs__subqueries" });
      for (const sq of this.subQueries) {
        this.renderSubQuery(list, sq);
      }
    }

    // Footer: done banner, error, or progress message
    if (this.phase === "done") {
      const banner = contentEl.createDiv({ cls: "ai-os-rs__done-banner" });
      banner.createSpan({ text: "✓" });
      banner.createSpan({ text: "Research complete — report written to vault" });
    } else if (this.phase === "error" && this.errorMessage) {
      contentEl.createDiv({ cls: "ai-os-rs__error", text: this.errorMessage });
    } else if (this.progressMessage) {
      contentEl.createDiv({
        cls: "ai-os-rs__footer",
        text: this.progressMessage,
      });
    }
  }

  private renderStep(parent: HTMLElement, phase: Phase): void {
    const currentIdx = PHASE_STEPS.indexOf(this.phase);
    const phaseIdx = PHASE_STEPS.indexOf(phase);
    const allDone = this.phase === "done";
    const done = allDone || (currentIdx !== -1 && currentIdx > phaseIdx);
    const active = !allDone && this.phase === phase;

    const row = parent.createDiv({
      cls: `ai-os-rs__step${done ? " is-done" : active ? " is-active" : ""}`,
    });

    const iconWrap = row.createDiv({ cls: "ai-os-rs__step-icon" });
    if (done) {
      iconWrap.createSpan({ cls: "ai-os-rs__step-check", text: "✓" });
    } else if (active) {
      iconWrap.createDiv({ cls: "ai-os-rs__step-spinner" });
    } else {
      iconWrap.createDiv({ cls: "ai-os-rs__step-dot" });
    }

    row.createSpan({
      cls: "ai-os-rs__step-label",
      text: PHASE_LABELS[phase],
    });
  }

  private renderSubQuery(parent: HTMLElement, sq: SubQueryState): void {
    const isDone = sq.status === "done";
    const isActive =
      sq.status === "searching" ||
      (sq.status === "pending" && this.phase === "researching");

    const card = parent.createDiv({
      cls: `ai-os-rs__sq${isDone ? " is-done" : isActive ? " is-active" : ""}`,
    });

    // Header row: badge + status icon
    const hdr = card.createDiv({ cls: "ai-os-rs__sq-header" });
    hdr.createSpan({
      cls: `ai-os-rs__badge ai-os-rs__badge--${sq.target}`,
      text: sq.target.toUpperCase(),
    });

    const statusIcon = hdr.createDiv({ cls: "ai-os-rs__sq-status-icon" });
    if (isDone) {
      statusIcon.createSpan({ cls: "ai-os-rs__sq-check", text: "✓" });
    } else if (isActive) {
      statusIcon.createDiv({ cls: "ai-os-rs__sq-mini-spinner" });
    }

    // Sub-query text
    card.createDiv({
      cls: "ai-os-rs__sq-text",
      text: sq.text.length > 120 ? sq.text.slice(0, 119) + "…" : sq.text,
    });

    // Per-URL fetch rows (web sub-queries only)
    if (sq.target === "web" && sq.fetches.length > 0) {
      const fetchesEl = card.createDiv({ cls: "ai-os-rs__sq-fetches" });
      for (const f of sq.fetches) {
        const row = fetchesEl.createDiv({
          cls: `ai-os-rs__sq-fetch${f.status === "done" ? " is-done" : f.status === "fetching" ? " is-fetching" : ""}`,
        });
        const iconWrap = row.createDiv({ cls: "ai-os-rs__sq-fetch-icon" });
        if (f.status === "done") {
          iconWrap.createSpan({ cls: "ai-os-rs__sq-fetch-check", text: "✓" });
        } else if (f.status === "fetching") {
          iconWrap.createDiv({ cls: "ai-os-rs__sq-mini-spinner" });
        } else {
          iconWrap.createDiv({ cls: "ai-os-rs__step-dot" });
        }
        const domain = extractDomain(f.url);
        row.createSpan({
          cls: "ai-os-rs__sq-fetch-domain",
          text: domain,
          title: f.url,
        });
        if (f.status === "done" && f.chunks !== undefined && f.chunks > 0) {
          row.createSpan({
            cls: "ai-os-rs__sq-fetch-chunks",
            text: `${f.chunks}`,
          });
        }
      }
    }

    // Vault chunk summary (done only)
    if (isDone && sq.target === "vault" && sq.chunkCount !== undefined) {
      card.createDiv({
        cls: "ai-os-rs__sq-chunks",
        text: `${sq.chunkCount} passage${sq.chunkCount !== 1 ? "s" : ""} retrieved`,
      });
    }
  }
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 40);
  }
}

export async function activateResearchView(
  plugin: AiOsPlugin,
): Promise<ResearchStatusView | null> {
  const { workspace } = plugin.app;
  let leaf = workspace.getLeavesOfType(VIEW_TYPE_RESEARCH)[0];
  if (!leaf) {
    leaf = workspace.getRightLeaf(false) ?? workspace.getLeaf(true);
    await leaf.setViewState({ type: VIEW_TYPE_RESEARCH, active: true });
  }
  workspace.revealLeaf(leaf);
  return getResearchView(plugin);
}

export function getResearchView(plugin: AiOsPlugin): ResearchStatusView | null {
  const leaf = plugin.app.workspace.getLeavesOfType(VIEW_TYPE_RESEARCH)[0];
  return leaf?.view instanceof ResearchStatusView ? leaf.view : null;
}
