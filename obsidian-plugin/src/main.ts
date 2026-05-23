// AI OS plugin entry. Lifecycle + wiring only.
// Headline capabilities live in `src/surfacing` and `src/research`.
// All LLM/retrieval logic lives in the orchestrator (ADR-0005, ADR-0009).
import {
  MarkdownView,
  Menu,
  Notice,
  Plugin,
  TAbstractFile,
  TFile,
} from "obsidian";
import { AiOsSettings, AiOsSettingTab, DEFAULT_SETTINGS } from "./settings";
import { ApiError, OrchestratorClient } from "./api";
import {
  SurfacingView,
  VIEW_TYPE_SURFACING,
  activateSurfacingView,
  fileRelpath,
  getOpenSurfacingView,
} from "./surfacing";
import { ResearchQueryModal, stripSpecNote, writeReportNote } from "./research";

interface SurfaceOptions {
  /** Bypass the debounce window — fire immediately. */
  force?: boolean;
}

interface ResearchRunOptions {
  specNotePath?: string;
  maxSubQueries?: number;
  onProgress?: (message: string) => void;
}

export default class AiOsPlugin extends Plugin {
  settings: AiOsSettings = { ...DEFAULT_SETTINGS };
  api: OrchestratorClient = new OrchestratorClient(
    () => this.settings.backendUrl,
  );

  private surfaceTimer: number | null = null;
  private surfaceInflight = 0;
  private lastSurfaceKey: string | null = null;
  private researchStatusEl: HTMLElement | null = null;

  async onload(): Promise<void> {
    await this.loadSettings();

    this.registerView(
      VIEW_TYPE_SURFACING,
      (leaf) => new SurfacingView(leaf, this),
    );

    this.addRibbonIcon("search", "Open AI OS related panel", () => {
      void activateSurfacingView(this);
    });

    this.addCommand({
      id: "open-surfacing-panel",
      name: "Open related panel",
      callback: () => {
        void activateSurfacingView(this);
      },
    });

    this.addCommand({
      id: "refresh-surfacing",
      name: "Refresh related panel",
      callback: () => {
        const active = this.app.workspace.getActiveViewOfType(MarkdownView);
        if (!active?.file) {
          new Notice("Open a Markdown note first.");
          return;
        }
        this.requestSurface(active.file, { force: true });
      },
    });

    this.addCommand({
      id: "deep-research",
      name: "Deep research",
      callback: () => {
        new ResearchQueryModal(this.app, this).open();
      },
    });

    this.addCommand({
      id: "deep-research-from-selection",
      name: "Deep research from selection",
      editorCallback: (editor) => {
        const selection = editor.getSelection().trim();
        new ResearchQueryModal(this.app, this, {
          initialQuery: selection,
        }).open();
      },
    });

    this.addCommand({
      id: "deep-research-from-active-note",
      name: "Deep research from active note (use as spec)",
      checkCallback: (checking) => {
        const file = this.app.workspace.getActiveFile();
        const eligible = !!file && file.extension === "md";
        if (checking) return eligible;
        if (!file) return false;
        void this.openResearchFromNote(file);
        return true;
      },
    });

    this.addCommand({
      id: "check-backend-health",
      name: "Check orchestrator health",
      callback: () => {
        void this.checkHealth();
      },
    });

    this.addSettingTab(new AiOsSettingTab(this.app, this));
    this.researchStatusEl = this.addStatusBarItem();
    this.researchStatusEl.hide();

    this.registerEvent(
      this.app.workspace.on("active-leaf-change", () =>
        this.onActiveLeafChange(),
      ),
    );

    this.registerEvent(
      this.app.workspace.on("file-menu", (menu: Menu, file: TAbstractFile) =>
        this.onFileMenu(menu, file),
      ),
    );

    console.log("AI OS plugin loaded.");
  }

  private onFileMenu(menu: Menu, file: TAbstractFile): void {
    if (!(file instanceof TFile) || file.extension !== "md") return;
    menu.addItem((item) =>
      item
        .setTitle("Deep research using this note")
        .setIcon("search")
        .onClick(() => {
          void this.openResearchFromNote(file);
        }),
    );
  }

  private async openResearchFromNote(file: TFile): Promise<void> {
    try {
      const raw = await this.app.vault.cachedRead(file);
      const cleaned = stripSpecNote(raw);
      if (!cleaned.trim()) {
        new Notice(
          `${file.basename} has no body content after stripping metadata.`,
        );
        return;
      }
      new ResearchQueryModal(this.app, this, {
        initialQuery: cleaned,
        specNotePath: file.path,
      }).open();
    } catch (e) {
      new Notice(`Could not read ${file.path}: ${(e as Error).message}`);
    }
  }

  async onunload(): Promise<void> {
    if (this.surfaceTimer !== null) {
      window.clearTimeout(this.surfaceTimer);
      this.surfaceTimer = null;
    }
    console.log("AI OS plugin unloaded.");
  }

  async loadSettings(): Promise<void> {
    const stored = (await this.loadData()) as Partial<AiOsSettings> | null;
    this.settings = { ...DEFAULT_SETTINGS, ...(stored ?? {}) };
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  // ── Surfacing trigger (debounced) ──────────────────────────────────────────

  private onActiveLeafChange(): void {
    if (!this.settings.surfacingEnabled) return;
    const active = this.app.workspace.getActiveViewOfType(MarkdownView);
    if (!active?.file) return;
    this.requestSurface(active.file);
  }

  /**
   * Queue a /surface call for the given file. Debounced per the user setting,
   * unless `force` is set. Calls are de-duplicated by file path so a flurry of
   * leaf-change events collapses to a single request.
   */
  requestSurface(file: TFile, opts: SurfaceOptions = {}): void {
    if (!getOpenSurfacingView(this) && !opts.force) {
      // No panel is open; don't bother the backend.
      return;
    }

    if (this.surfaceTimer !== null) {
      window.clearTimeout(this.surfaceTimer);
      this.surfaceTimer = null;
    }

    const fire = () => {
      this.surfaceTimer = null;
      void this.runSurface(file);
    };

    if (opts.force || this.settings.surfaceDebounceMs <= 0) {
      fire();
    } else {
      this.surfaceTimer = window.setTimeout(
        fire,
        this.settings.surfaceDebounceMs,
      );
    }
  }

  private async runSurface(file: TFile): Promise<void> {
    const relpath = fileRelpath(file);
    const view = getOpenSurfacingView(this);
    if (!view) return;

    const callId = ++this.surfaceInflight;
    view.onLoading(relpath);

    try {
      const content = await this.app.vault.cachedRead(file);
      const response = await this.api.surface({
        relpath,
        content,
        k: this.settings.surfaceTopK,
      });
      // If a newer call has been queued in the meantime, drop this result.
      if (callId !== this.surfaceInflight) return;
      // Filter self-references — surfacing should only show related _other_ blocks.
      const results = response.results.filter((r) => r.relpath !== relpath);
      this.lastSurfaceKey = relpath;
      view.onResults(relpath, results);
    } catch (e) {
      if (callId !== this.surfaceInflight) return;
      view.onError(relpath, e);
    }
  }

  // ── Deep research runner ───────────────────────────────────────────────────

  async runDeepResearch(
    query: string,
    options: ResearchRunOptions = {},
  ): Promise<TFile | null> {
    const notice = new Notice(`Researching: ${truncate(query, 80)}…`, 0);
    const startedAt = Date.now();
    const progress = (message: string) => {
      options.onProgress?.(message);
      this.setResearchStatus(message);
      notice.setMessage(message);
    };
    progress(
      `Research started — retrieving, synthesising, and verifying citations (${formatElapsed(0)})`,
    );
    const timer = window.setInterval(() => {
      const elapsed = Date.now() - startedAt;
      progress(
        `Research still running — local inference is working (${formatElapsed(elapsed)})`,
      );
    }, 5000);
    try {
      const response = await this.api.research({
        query,
        k: this.settings.researchK,
        max_repair_attempts: this.settings.researchMaxRepairAttempts,
        max_sub_queries: options.maxSubQueries,
        decompose: settingToDecompose(this.settings.researchDecompose),
      });
      progress("Research complete — writing report note…");
      const file = await writeReportNote(this, response, options);
      window.clearInterval(timer);
      this.clearResearchStatus();
      notice.hide();
      new Notice(
        `Research complete — ${(response.pass_rate * 100).toFixed(0)}% citations verified` +
          (response.failures.length > 0
            ? ` (${response.failures.length} failures)`
            : ""),
      );
      return file;
    } catch (e) {
      window.clearInterval(timer);
      notice.hide();
      const msg =
        e instanceof ApiError
          ? `Orchestrator HTTP ${e.status}: ${e.body.slice(0, 200)}`
          : (e as Error).message;
      new Notice(`Research failed: ${msg}`);
      throw e;
    }
  }

  // ── Health probe ───────────────────────────────────────────────────────────

  async checkHealth(): Promise<void> {
    try {
      const h = await this.api.health();
      new Notice(
        `Orchestrator OK — vault=${h.vault ?? "?"} files=${h.file_count} chunks=${h.chunk_count}`,
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      new Notice(`Orchestrator unreachable: ${msg}`);
    }
  }

  private setResearchStatus(message: string): void {
    if (!this.researchStatusEl) return;
    this.researchStatusEl.setText(`AI OS: ${message}`);
    this.researchStatusEl.show();
  }

  private clearResearchStatus(): void {
    if (!this.researchStatusEl) return;
    this.researchStatusEl.setText("");
    this.researchStatusEl.hide();
  }
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins === 0) return `${secs}s`;
  return `${mins}m ${secs.toString().padStart(2, "0")}s`;
}

function settingToDecompose(
  value: "auto" | "always" | "never",
): "auto" | boolean {
  if (value === "always") return true;
  if (value === "never") return false;
  return "auto";
}
