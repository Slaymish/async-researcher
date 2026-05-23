// Proactive surfacing side panel — MVP §"Capability 1", ADR-0004.
//
// On active-leaf-change (debounced), send the active note's relpath + content
// to POST /surface and render the returned top-K related blocks. Each result is
// a click-through to `note#^id` — the `^id` lingua franca per ADR-0012.
import { ItemView, MarkdownView, Notice, TFile, WorkspaceLeaf } from "obsidian";
import type AiOsPlugin from "../main";
import type { SurfaceChunk } from "../api";
import { ApiError } from "../api";

export const VIEW_TYPE_SURFACING = "ai-os-surfacing";

type PanelStatus = "idle" | "loading" | "ready" | "error" | "empty";

export class SurfacingView extends ItemView {
  private bodyEl: HTMLElement | null = null;
  private statusEl: HTMLElement | null = null;
  private results: SurfaceChunk[] = [];
  private currentRelpath: string | null = null;
  private status: PanelStatus = "idle";
  private statusMessage = "";

  constructor(
    leaf: WorkspaceLeaf,
    private readonly plugin: AiOsPlugin,
  ) {
    super(leaf);
  }

  getViewType(): string {
    return VIEW_TYPE_SURFACING;
  }

  getDisplayText(): string {
    return "Related notes";
  }

  getIcon(): string {
    return "brain";
  }

  async onOpen(): Promise<void> {
    this.renderShell();
    // If a note is already active, kick off the first surface call.
    const active = this.app.workspace.getActiveViewOfType(MarkdownView);
    if (active?.file) {
      this.plugin.requestSurface(active.file);
    }
  }

  async onClose(): Promise<void> {
    this.contentEl.empty();
    this.bodyEl = null;
    this.statusEl = null;
  }

  /** Called by the plugin after each /surface call completes. */
  onResults(relpath: string, results: SurfaceChunk[]): void {
    this.currentRelpath = relpath;
    this.results = results;
    this.status = results.length === 0 ? "empty" : "ready";
    this.statusMessage = "";
    this.renderBody();
  }

  onLoading(relpath: string): void {
    this.currentRelpath = relpath;
    this.status = "loading";
    this.statusMessage = "";
    this.renderBody();
  }

  onError(relpath: string, err: unknown): void {
    this.currentRelpath = relpath;
    this.status = "error";
    if (err instanceof ApiError) {
      this.statusMessage = `HTTP ${err.status}`;
    } else if (err instanceof Error) {
      this.statusMessage = err.message;
    } else {
      this.statusMessage = "Unknown error";
    }
    this.renderBody();
  }

  private renderShell(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("ai-os-surfacing");

    const headerEl = contentEl.createDiv({ cls: "ai-os-surfacing__header" });
    headerEl.createDiv({ cls: "ai-os-surfacing__title", text: "Related notes" });
    headerEl
      .createEl("button", { cls: "ai-os-surfacing__refresh", text: "Refresh" })
      .addEventListener("click", () => {
        const active = this.app.workspace.getActiveViewOfType(MarkdownView);
        if (active?.file) this.plugin.requestSurface(active.file, { force: true });
      });

    this.renderThresholdControl(contentEl);

    this.statusEl = contentEl.createDiv({ cls: "ai-os-surfacing__status" });
    this.bodyEl = contentEl.createDiv({ cls: "ai-os-surfacing__body" });
    this.renderBody();
  }

  private renderThresholdControl(parent: HTMLElement): void {
    // Client-side score filter. The /surface call still returns top-K from the
    // backend; this only changes what's drawn, so dragging the slider is
    // instant and never re-hits the orchestrator.
    const rowEl = parent.createDiv({ cls: "ai-os-surfacing__threshold" });
    rowEl.createSpan({
      cls: "ai-os-surfacing__threshold-label",
      text: "Relevance threshold",
    });
    const sliderEl = rowEl.createEl("input", {
      cls: "ai-os-surfacing__threshold-slider",
      attr: {
        type: "range",
        min: "0",
        max: "1",
        step: "0.01",
        value: String(this.plugin.settings.surfaceMinScore),
      },
    }) as HTMLInputElement;
    const fmtScore = (v: number) => `${Math.round(v * 100)}%`;
    const valueEl = rowEl.createSpan({
      cls: "ai-os-surfacing__threshold-value",
      text: fmtScore(this.plugin.settings.surfaceMinScore),
    });
    sliderEl.addEventListener("input", () => {
      const v = Number.parseFloat(sliderEl.value);
      this.plugin.settings.surfaceMinScore = v;
      valueEl.setText(fmtScore(v));
      // Persist in the background; don't block re-render on disk write.
      void this.plugin.saveSettings();
      this.renderBody();
    });
  }

  private renderBody(): void {
    if (!this.bodyEl || !this.statusEl) return;
    this.bodyEl.empty();
    this.statusEl.empty();

    const subtitle = this.currentRelpath
      ? `For: ${noteBasename(this.currentRelpath)}`
      : "Open a note to see related content.";
    this.statusEl.createSpan({ text: subtitle });

    switch (this.status) {
      case "idle":
        return;
      case "loading":
        this.bodyEl.createDiv({ cls: "ai-os-surfacing__placeholder", text: "Finding related notes…" });
        return;
      case "empty":
        this.bodyEl.createDiv({
          cls: "ai-os-surfacing__placeholder",
          text: "No related content found.",
        });
        return;
      case "error":
        this.bodyEl.createDiv({
          cls: "ai-os-surfacing__placeholder ai-os-surfacing__placeholder--error",
          text: this.statusMessage || "Surfacing failed.",
        });
        return;
    }

    const minScore = this.plugin.settings.surfaceMinScore;
    const visible = this.results.filter((c) => c.score >= minScore);
    const hidden = this.results.length - visible.length;
    if (hidden > 0) {
      this.statusEl.createSpan({
        cls: "ai-os-surfacing__status-detail",
        text: ` — showing ${visible.length} of ${this.results.length} (${hidden} below ${Math.round(minScore * 100)}%)`,
      });
    }
    if (visible.length === 0) {
      this.bodyEl.createDiv({
        cls: "ai-os-surfacing__placeholder",
        text: `All ${this.results.length} results are below the relevance threshold. Lower the slider to show them.`,
      });
      return;
    }

    for (const chunk of visible) {
      const cardEl = this.bodyEl.createDiv({ cls: "ai-os-surfacing__card" });

      const headEl = cardEl.createDiv({ cls: "ai-os-surfacing__card-head" });
      headEl.createSpan({
        cls: "ai-os-surfacing__card-name",
        text: noteBasename(chunk.relpath),
      });
      if (chunk.kind && chunk.kind !== "paragraph") {
        headEl.createSpan({
          cls: "ai-os-surfacing__card-kind",
          text: chunk.kind.replace("_", " "),
        });
      }

      cardEl.createDiv({
        cls: "ai-os-surfacing__card-path",
        text: chunk.relpath,
      });

      cardEl.createDiv({
        cls: "ai-os-surfacing__card-text",
        text: snippet(chunk.text),
      });

      cardEl.addEventListener("click", () => {
        this.openChunk(chunk).catch((e) => {
          new Notice(`Could not open ${chunk.relpath}: ${(e as Error).message}`);
        });
      });
    }
  }

  private async openChunk(chunk: SurfaceChunk): Promise<void> {
    // `relpath` is vault-relative; resolve via the metadata cache so we can
    // jump to the `^id` block reference.
    const target = `${chunk.relpath}#^${chunk.block_id}`;
    await this.app.workspace.openLinkText(target, "", false);
  }
}

function snippet(text: string, max = 320): string {
  // Strip the visual noise that's distracting in a preview but not the content:
  // ingestion-injected block IDs (`^ai-…`), code-fence delimiters, image
  // syntax, and bold/italic/inline-code markers. We're not parsing markdown —
  // we're flattening it for a read-only preview tile.
  const plain = text
    .replace(/\^ai-[0-9a-f]+/gi, "") // ingestion block-id markers (ADR-0012)
    .replace(/```+[a-zA-Z0-9_-]*\n?/g, "") // fenced-code delimiters
    .replace(/!\[([^\]]*)]\([^)]*\)/g, "$1") // images → alt text
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1") // inline links → label
    .replace(/(\*\*|__)(.*?)\1/g, "$2") // bold
    .replace(/(\*|_)(?=\S)(.*?\S)\1/g, "$2") // italic
    .replace(/`([^`]+)`/g, "$1") // inline code
    .replace(/\s+/g, " ")
    .trim();
  return plain.length > max ? `${plain.slice(0, max - 1)}…` : plain;
}

export async function activateSurfacingView(plugin: AiOsPlugin): Promise<void> {
  const { workspace } = plugin.app;
  let leaf = workspace.getLeavesOfType(VIEW_TYPE_SURFACING)[0];
  if (!leaf) {
    const right = workspace.getRightLeaf(false);
    if (!right) return;
    leaf = right;
    await leaf.setViewState({ type: VIEW_TYPE_SURFACING, active: true });
  }
  workspace.revealLeaf(leaf);
}

export function getOpenSurfacingView(plugin: AiOsPlugin): SurfacingView | null {
  const leaf = plugin.app.workspace.getLeavesOfType(VIEW_TYPE_SURFACING)[0];
  const view = leaf?.view;
  return view instanceof SurfacingView ? view : null;
}

/**
 * Resolves the vault-relative path of a file using forward slashes — what the
 * orchestrator's DuckDB/LightRAG indices store as `relpath`.
 */
export function fileRelpath(file: TFile): string {
  return file.path;
}

function noteBasename(relpath: string): string {
  const last = relpath.split("/").pop() ?? relpath;
  return last.replace(/\.md$/i, "");
}
