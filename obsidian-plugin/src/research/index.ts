// Deep research query → new note in vault — MVP §"Capability 2", ADR-0013.
//
// 1. User types a research question in a modal.
// 2. Plugin POSTs to /research; orchestrator does retrieve → synth → verify →
//    bounded repair and returns assembled Markdown with [[note#^id]] citations.
// 3. Plugin writes the report to the configured output folder as a new note.
import {
  App,
  ButtonComponent,
  FuzzySuggestModal,
  Modal,
  Notice,
  Setting,
  TextAreaComponent,
  TFile,
  normalizePath,
} from "obsidian";
import type AiOsPlugin from "../main";
import type { ResearchResponse } from "../api";

export interface ResearchModalOptions {
  /** Pre-fill the question textarea. */
  initialQuery?: string;
  /** Vault path of the note this query came from; recorded in the report
   *  frontmatter so the user can trace report → spec. */
  specNotePath?: string;
}

export class ResearchQueryModal extends Modal {
  private query = "";
  private maxSubQueries = 5;
  private specNotePath: string | null;
  private specSourceEl: HTMLElement | null = null;
  private textArea: TextAreaComponent | null = null;
  private busy = false;
  private submitBtn: ButtonComponent | null = null;
  private statusEl: HTMLElement | null = null;
  private statusDetailEl: HTMLElement | null = null;

  constructor(
    app: App,
    private readonly plugin: AiOsPlugin,
    options: ResearchModalOptions | string = "",
  ) {
    super(app);
    const opts: ResearchModalOptions =
      typeof options === "string" ? { initialQuery: options } : options;
    this.query = opts.initialQuery ?? "";
    this.specNotePath = opts.specNotePath ?? null;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("ai-os-research-modal");
    contentEl.createEl("h2", { text: "Research" });

    new Setting(contentEl)
      .setName("Question")
      .setDesc("What would you like to research across your vault?")
      .addTextArea((text: TextAreaComponent) => {
        this.textArea = text;
        text.setPlaceholder(
          "e.g. What have I noted about deterministic citation pipelines?",
        );
        text.setValue(this.query);
        text.inputEl.rows = 10;
        text.inputEl.style.width = "100%";
        text.onChange((value) => {
          this.query = value;
          // Editing detaches the textarea from any loaded spec note —
          // the recorded `spec_note` would otherwise misrepresent the input.
          if (this.specNotePath !== null) {
            this.specNotePath = null;
            this.renderSpecSource();
          }
        });
        text.inputEl.focus();
      });

    // "Load from note" affordances. Two paths: pick any vault file via fuzzy
    // suggest, or grab the current active note in one click.
    const specRow = new Setting(contentEl)
      .setName("Use a note as spec")
      .setDesc(
        "Load the content of an existing note into the question above. " +
          "Frontmatter and ingestion block-ids are stripped.",
      );
    specRow.addButton((btn) =>
      btn.setButtonText("Pick note…").onClick(() => {
        new NoteSuggestModal(this.app, (file) => {
          void this.loadFromNote(file);
        }).open();
      }),
    );
    specRow.addButton((btn) =>
      btn.setButtonText("Use active note").onClick(() => {
        const file = this.app.workspace.getActiveFile();
        if (!file || file.extension !== "md") {
          new Notice("Open a Markdown note first.");
          return;
        }
        void this.loadFromNote(file);
      }),
    );

    this.specSourceEl = contentEl.createDiv({
      cls: "ai-os-research-modal__spec-source",
    });
    this.renderSpecSource();

    new Setting(contentEl)
      .setName("Sub-questions")
      .setDesc(
        "Maximum number of focused sub-questions to research. Lower values are faster.",
      )
      .addSlider((slider) => {
        slider
          .setLimits(1, 5, 1)
          .setValue(this.maxSubQueries)
          .setDynamicTooltip()
          .onChange((value) => {
            this.maxSubQueries = value;
          });
      });

    const buttonRow = new Setting(contentEl);
    buttonRow.addButton((btn) => {
      this.submitBtn = btn
        .setButtonText("Start research")
        .setCta()
        .onClick(() => {
          void this.submit();
        });
    });
    buttonRow.addButton((btn) =>
      btn.setButtonText("Close").onClick(() => this.close()),
    );

    const statusWrap = contentEl.createDiv({
      cls: "ai-os-research-modal__status",
    });
    this.statusEl = statusWrap.createDiv({
      cls: "ai-os-research-modal__status-title",
    });
    this.statusDetailEl = statusWrap.createDiv({
      cls: "ai-os-research-modal__status-detail",
    });
    this.setStatus("", "Enter a question to begin.");
  }

  private async loadFromNote(file: TFile): Promise<void> {
    try {
      const raw = await this.app.vault.cachedRead(file);
      const cleaned = stripSpecNote(raw);
      if (!cleaned.trim()) {
        new Notice(
          `${file.basename} has no body content after stripping metadata.`,
        );
        return;
      }
      this.query = cleaned;
      // Set programmatically AFTER, so the onChange handler doesn't blow away
      // the spec source we're about to record.
      this.specNotePath = file.path;
      if (this.textArea) {
        this.textArea.setValue(cleaned);
        this.textArea.inputEl.focus();
      }
      this.renderSpecSource();
    } catch (e) {
      new Notice(`Could not read ${file.path}: ${(e as Error).message}`);
    }
  }

  private renderSpecSource(): void {
    if (!this.specSourceEl) return;
    this.specSourceEl.empty();
    if (!this.specNotePath) return;
    this.specSourceEl.createSpan({
      cls: "ai-os-research-modal__spec-source-label",
      text: "Spec note: ",
    });
    this.specSourceEl.createSpan({
      cls: "ai-os-research-modal__spec-source-path",
      text: this.specNotePath,
    });
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private async submit(): Promise<void> {
    if (this.busy) return;
    const query = this.query.trim();
    if (!query) {
      new Notice("Enter a research question first.");
      return;
    }

    this.busy = true;
    this.submitBtn?.setDisabled(true);
    this.setStatus(
      "Starting…",
      "Connecting to your local backend.",
    );

    try {
      const file = await this.plugin.runDeepResearch(query, {
        specNotePath: this.specNotePath ?? undefined,
        maxSubQueries: this.maxSubQueries,
        onProgress: (message) => {
          this.setStatus("Researching…", message);
        },
      });
      this.setStatus("Done", "Opening your report…");
      this.close();
      if (file) {
        await this.app.workspace.getLeaf(true).openFile(file);
      }
    } catch (e) {
      this.setStatus("Research failed", (e as Error).message);
      this.busy = false;
      this.submitBtn?.setDisabled(false);
    }
  }

  private setStatus(title: string, detail = ""): void {
    if (this.statusEl) this.statusEl.setText(title);
    if (this.statusDetailEl) this.statusDetailEl.setText(detail);
  }
}

export interface WriteReportOptions {
  /** Vault path of the note the user used as a research spec, if any. */
  specNotePath?: string;
}

/**
 * Write the research report to the vault. Returns the new file.
 * Note: the assembled markdown already contains [[note#^id]] citations — we
 * don't post-process them. Verification metadata is stored in frontmatter for
 * later auditing.
 */
export async function writeReportNote(
  plugin: AiOsPlugin,
  response: ResearchResponse,
  options: WriteReportOptions = {},
): Promise<TFile> {
  const folder = normalizeFolder(plugin.settings.researchOutputFolder);
  await ensureFolder(plugin, folder);

  const title = titleForReport(response, options);
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const baseName = `${stamp} ${title}`;
  const path = await nextAvailablePath(plugin, folder, baseName);

  const content = buildReportNote(
    response,
    options,
    plugin.settings.researchShowDebug,
  );
  return plugin.app.vault.create(path, content);
}

function titleForReport(
  response: ResearchResponse,
  options: WriteReportOptions,
): string {
  // When a spec note drove the query, prefer its basename over a slice of the
  // multi-paragraph spec body — much friendlier in the file picker.
  if (options.specNotePath) {
    const stem = options.specNotePath.split("/").pop() ?? options.specNotePath;
    const noExt = stem.replace(/\.md$/i, "");
    return sanitizeFileName(noExt);
  }
  return sanitizeFileName(response.query);
}

function buildReportNote(
  response: ResearchResponse,
  options: WriteReportOptions,
  showDebug: boolean,
): string {
  const now = new Date().toISOString();
  const lines = [
    "---",
    `ai-os-query: ${jsonString(response.query)}`,
    `ai-os-generated: ${jsonString(now)}`,
    `ai-os-attempts: ${response.attempts}`,
    `ai-os-pass-rate: ${response.pass_rate.toFixed(4)}`,
    `ai-os-failures: ${response.failures.length}`,
  ];
  if (options.specNotePath) {
    // Wikilink form so the report is browsable from the spec note's backlinks.
    lines.push(`ai-os-spec-note: "[[${options.specNotePath}]]"`);
  }
  if (response.atomizer) {
    lines.push(`ai-os-atomizer-decompose: ${response.atomizer.decompose}`);
    lines.push(
      `ai-os-atomizer-rationale: ${jsonString(response.atomizer.rationale)}`,
    );
  }
  if (response.executions?.length) {
    lines.push(`ai-os-executors: ${response.executions.length}`);
  }
  lines.push("tags:", "  - ai-os/research-report", "---", "");
  const frontmatter = lines.join("\n");

  const body = response.markdown.trimEnd();
  const failuresSection =
    response.failures.length === 0 ? "" : buildFailuresSection(response);
  const debugSection = showDebug ? buildDebugSection(response) : "";

  return `${frontmatter}${body}${failuresSection}${debugSection}\n`;
}

function buildFailuresSection(response: ResearchResponse): string {
  return [
    "",
    "",
    "## ⚠ Verification failures",
    "",
    "The citation engine could not fully verify the following claims.",
    "",
    ...response.failures.map(
      (f) =>
        `- **[${f.kind}]** ${f.section || "(no section)"}: ${f.detail}` +
        (f.claim ? `\n  - claim: ${f.claim}` : "") +
        (f.block_id ? `\n  - block: ^${f.block_id}` : ""),
    ),
  ].join("\n");
}

function buildDebugSection(response: ResearchResponse): string {
  // v0.2.2 diagnostic shim. Renders the Atomizer's rationale + a per-Executor
  // retrieval log so the user can audit why specific chunks were chosen.
  // Wrapped in a collapsed `<details>` block so it doesn't dominate the
  // reading flow on every report.
  const lines: string[] = ["", "", "<details>", "<summary>Debug</summary>", ""];
  if (response.atomizer) {
    lines.push(
      `**Atomizer:** \`decompose=${response.atomizer.decompose}\` — ${response.atomizer.rationale}`,
      "",
    );
  }
  for (const [i, ex] of (response.executions ?? []).entries()) {
    lines.push(
      `### Executor ${i + 1}: ${ex.sub_query}`,
      "",
      `*${ex.rationale}*  ·  attempts: ${ex.attempts}  ·  pass rate: ${(ex.pass_rate * 100).toFixed(0)}%`,
      "",
    );
    if (ex.chunks.length === 0) {
      lines.push("_(no chunks retrieved)_", "");
    } else {
      lines.push("| Score | Block | Source |", "|---|---|---|");
      for (const c of ex.chunks) {
        lines.push(
          `| ${c.score.toFixed(3)} | \`^${c.block_id}\` | [[${c.relpath}#^${c.block_id}]] |`,
        );
      }
      lines.push("");
    }
    if (ex.failures.length > 0) {
      lines.push(
        "Failures:",
        ...ex.failures.map(
          (f) =>
            `- **[${f.kind}]** ${f.section || "(no section)"}: ${f.detail}`,
        ),
        "",
      );
    }
  }
  lines.push("</details>");
  return lines.join("\n");
}

// ── Vault file utilities (lifted from the researcher plugin) ────────────────

export function sanitizeFileName(value: string): string {
  return (
    value
      .replace(/[\\/:*?"<>|#^[\]]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80) || "Untitled research"
  );
}

export function normalizeFolder(value: string): string {
  return normalizePath(value.trim()).replace(/^\/+|\/+$/g, "");
}

export async function ensureFolder(
  plugin: AiOsPlugin,
  folder: string,
): Promise<void> {
  if (!folder) return;
  const parts = folder.split("/").filter(Boolean);
  let current = "";
  for (const part of parts) {
    current = current ? `${current}/${part}` : part;
    if (!plugin.app.vault.getAbstractFileByPath(current)) {
      await plugin.app.vault.createFolder(current);
    }
  }
}

export async function nextAvailablePath(
  plugin: AiOsPlugin,
  folder: string,
  baseName: string,
): Promise<string> {
  let suffix = 0;
  while (true) {
    const fileName =
      suffix === 0 ? `${baseName}.md` : `${baseName} ${suffix + 1}.md`;
    const path = normalizePath(folder ? `${folder}/${fileName}` : fileName);
    if (!plugin.app.vault.getAbstractFileByPath(path)) return path;
    suffix += 1;
  }
}

function jsonString(value: string): string {
  return JSON.stringify(value);
}

/**
 * Pre-process a vault note before using it as a research spec. Removes:
 *  - YAML frontmatter at the top of the file
 *  - ingestion-injected `^ai-…` block-id markers (ADR-0012) — they're noise
 *    to the synthesis model and trigger the verifier's "treat as citation"
 *    heuristic on the wrong text.
 * Leaves the rest of the markdown intact — headings, lists, code blocks all
 * still carry meaning the LLM can use.
 */
export function stripSpecNote(raw: string): string {
  let body = raw;
  // YAML frontmatter is delimited by `---` on the first line and a closing
  // `---` line. Tolerate a trailing newline before the opener.
  const fmMatch = body.match(/^\s*---\n[\s\S]*?\n---\n?/);
  if (fmMatch) body = body.slice(fmMatch[0].length);
  body = body.replace(/\s*\^ai-[0-9a-f]+/gi, "");
  return body.trim();
}

class NoteSuggestModal extends FuzzySuggestModal<TFile> {
  constructor(
    app: App,
    private readonly onPick: (file: TFile) => void,
  ) {
    super(app);
    this.setPlaceholder("Pick a note to use as the research spec…");
  }

  getItems(): TFile[] {
    return this.app.vault.getMarkdownFiles();
  }

  getItemText(file: TFile): string {
    return file.path;
  }

  onChooseItem(file: TFile): void {
    this.onPick(file);
  }
}
