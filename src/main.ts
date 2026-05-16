import {
  App,
  ButtonComponent,
  Editor,
  FileSystemAdapter,
  ItemView,
  MarkdownView,
  Menu,
  Modal,
  Notice,
  Plugin,
  PluginSettingTab,
  Setting,
  TAbstractFile,
  TFile,
  WorkspaceLeaf,
  normalizePath,
} from "obsidian";
import { spawn } from "child_process";
import { isAbsolute, join } from "path";
import { getLlm, LLM_PROVIDERS, type LlmProviderKind } from "./llm";

const VIEW_TYPE_RESEARCHER = "researcher-view";

const STATUS_ORDER = [
  "backlog",
  "to-refine",
  "to-research",
  "researching",
  "completed",
] as const;

type ResearchStatus = (typeof STATUS_ORDER)[number];

type ResearchPriority = "high" | "normal" | "low";
const PRIORITY_ORDER: Record<ResearchPriority, number> = { high: 0, normal: 1, low: 2 };

interface ResearcherSettings {
  researchFolder: string;
  outputFolder: string;
  runsFolder: string;
  sidecarCommand: string;
  sidecarScriptPath: string;
  llmProvider: LlmProviderKind;
  llmBaseUrl: string;
  llmApiKey: string;
  llmModel: string;
}

interface QuestionProgress {
  answered: number;
  total: number;
}

interface ResearchItem {
  id: string;
  title: string;
  status: ResearchStatus;
  file: TFile;
  outputLink?: string;
  questionProgress: QuestionProgress;
  latestRun?: ResearchRunSummary;
  priority: ResearchPriority;
  tags: string[];
}

interface LlmProvider {
  generateQuestions(context: string): Promise<string[]>;
}

type ResearchRunStatus =
  | "queued"
  | "planning"
  | "searching"
  | "fetching"
  | "synthesizing"
  | "completed"
  | "failed";

interface ResearchRunProgress {
  step: ResearchRunStatus;
  message: string;
  percent: number;
}

interface ResearchRunRecord {
  id: string;
  notePath: string;
  noteTitle: string;
  runFolder: string;
  reportPath: string;
  createdAt: string;
  updatedAt: string;
  status: ResearchRunStatus;
  progress: ResearchRunProgress;
  request: {
    context: string;
    llmProvider: LlmProviderKind;
    llmBaseUrl: string;
    llmModel: string;
  };
}

interface ResearchRunSummary {
  id: string;
  status: ResearchRunStatus;
  message: string;
  percent: number;
  runFolder: string;
  reportPath: string;
  updatedAt: string;
}

const DEFAULT_SETTINGS: ResearcherSettings = {
  researchFolder: "Research Ideas",
  outputFolder: "Research Outputs",
  runsFolder: "Research Runs",
  sidecarCommand: "python3",
  sidecarScriptPath: "",
  llmProvider: "ollama",
  llmBaseUrl: "http://localhost:11434/v1",
  llmApiKey: "",
  llmModel: "",
};

const STATUS_LABELS: Record<ResearchStatus, string> = {
  backlog: "Backlog",
  "to-refine": "To Refine",
  "to-research": "To Research",
  researching: "Researching",
  completed: "Completed",
};

const PLACEHOLDER_QUESTIONS = [
  "What outcome would make this research useful?",
  "What context, constraints, or prior notes should shape the research?",
  "Which related notes or sources should be considered first?",
];

function isResearchStatus(value: unknown): value is ResearchStatus {
  return typeof value === "string" && STATUS_ORDER.includes(value as ResearchStatus);
}

function isLlmProviderKind(value: unknown): value is LlmProviderKind {
  return typeof value === "string" && value in LLM_PROVIDERS;
}

function nowIso() {
  return new Date().toISOString();
}

function generateResearchId() {
  return `research-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function sanitizeFileName(value: string) {
  return value
    .replace(/[\\/:*?"<>|#^[\]]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80) || "Untitled research idea";
}

function slugify(value: string) {
  return sanitizeFileName(value).replace(/\s+/g, "-").toLowerCase();
}

function normalizeFolder(value: string) {
  return normalizePath(value.trim()).replace(/^\/+|\/+$/g, "");
}

function frontmatterValue(value: string) {
  return JSON.stringify(value);
}

function buildResearchNote(title: string, description: string, settings: ResearcherSettings) {
  const timestamp = nowIso();
  const lines = [
    "---",
    "research-status: backlog",
    `research-id: ${frontmatterValue(generateResearchId())}`,
    `research-created: ${frontmatterValue(timestamp)}`,
    `research-updated: ${frontmatterValue(timestamp)}`,
    "tags:",
    "  - research/idea",
    "---",
    "",
    `# ${title}`,
    "",
  ];

  if (description.trim()) {
    lines.push(description.trim(), "");
  }

  lines.push("## Clarifying questions", "", "## Links", "");

  if (settings.outputFolder.trim()) {
    lines.push("<!-- Research outputs will be linked here when generated. -->", "");
  }

  return lines.join("\n");
}

function runTimestamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function getVaultBasePath(app: App) {
  const adapter = app.vault.adapter;
  return adapter instanceof FileSystemAdapter ? adapter.getBasePath() : null;
}

class ResearchQuestionProvider implements LlmProvider {
  constructor(private readonly settings: ResearcherSettings) {}

  async generateQuestions(context: string): Promise<string[]> {
    if (!this.settings.llmModel.trim()) return PLACEHOLDER_QUESTIONS;

    const llm = getLlm(this.settings);
    const raw = await llm(
      "You generate concise clarifying questions for a research assistant. Return only JSON.",
      [
        "Given this Obsidian research idea note, produce 3-5 clarifying questions.",
        "Return a JSON array of strings. Do not include markdown or commentary.",
        "",
        context.trim(),
      ].join("\n"),
      { expectJson: true, temperature: 0.2 },
    );

    const parsed = parseQuestionArray(raw);
    if (parsed.length === 0) {
      throw new Error("The LLM returned no usable questions.");
    }
    return parsed;
  }
}

function parseQuestionArray(raw: string) {
  const trimmed = raw.trim();
  const candidates = [
    trimmed,
    trimmed.match(/```(?:json)?\s*([\s\S]*?)```/)?.[1]?.trim(),
    trimmed.match(/\[[\s\S]*\]/)?.[0],
  ].filter((value): value is string => Boolean(value));

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate) as unknown;
      if (!Array.isArray(parsed)) continue;
      return parsed
        .filter((value): value is string => typeof value === "string")
        .map((value) => value.trim())
        .filter(Boolean)
        .slice(0, 5);
    } catch {
      // Try the next defensive parse candidate.
    }
  }

  return [];
}

class ResearchQueue {
  constructor(
    private readonly plugin: ResearcherPlugin,
    private readonly llmProvider: LlmProvider,
  ) {}

  async generateQuestionsForFile(file: TFile) {
    if (!(await this.plugin.store.isResearchFile(file))) {
      new Notice("The note is not a research idea.");
      return;
    }
    try {
      const context = await this.plugin.store.readResearchContext(file);
      const questions = await this.llmProvider.generateQuestions(context);
      await this.plugin.store.insertQuestions(file, questions);
      await this.plugin.refreshViews();
      new Notice(
        this.plugin.settings.llmModel.trim()
          ? "Generated clarifying questions."
          : "Inserted placeholder questions. Configure a model to use the LLM.",
      );
    } catch (error) {
      new Notice(`Could not generate questions: ${(error as Error).message}`);
    }
  }

  async generateQuestionsForActiveNote() {
    const file = this.plugin.getActiveMarkdownFile();
    if (!file) {
      new Notice("Open a research note before inserting questions.");
      return;
    }
    await this.generateQuestionsForFile(file);
  }
}

class ResearchParser {
  parseQuestionProgress(content: string): QuestionProgress {
    const section = this.sectionContent(content, "Clarifying questions");
    if (!section.trim()) return { answered: 0, total: 0 };

    const questionMatches = [...section.matchAll(/^- \[[ xX-]\]\s+(.+)$/gm)];
    const total = questionMatches.length;
    if (total === 0) return { answered: 0, total: 0 };

    let answered = 0;
    for (let index = 0; index < questionMatches.length; index += 1) {
      const current = questionMatches[index];
      const next = questionMatches[index + 1];
      const start = (current.index ?? 0) + current[0].length;
      const end = next?.index ?? section.length;
      const answerBlock = section.slice(start, end);
      if (/Answer:\s*\S/i.test(answerBlock)) answered += 1;
    }

    return { answered, total };
  }

  private sectionContent(content: string, heading: string) {
    const lines = content.split("\n");
    const headingPattern = new RegExp(
      `^##\\s+${heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`,
      "i",
    );
    const startIndex = lines.findIndex((line) => headingPattern.test(line));
    if (startIndex === -1) return "";

    const endIndex = lines.findIndex(
      (line, index) => index > startIndex && /^##\s+/.test(line),
    );
    return lines.slice(startIndex + 1, endIndex === -1 ? undefined : endIndex).join("\n");
  }
}

class ResearchStore {
  private readonly parser = new ResearchParser();

  constructor(
    private readonly app: App,
    private readonly plugin: ResearcherPlugin,
  ) {}

  async list(): Promise<ResearchItem[]> {
    const files = this.app.vault.getMarkdownFiles();
    const items: ResearchItem[] = [];

    for (const file of files) {
      if (!(await this.isResearchFile(file))) continue;
      const cache = this.app.metadataCache.getFileCache(file);
      const frontmatter = cache?.frontmatter ?? {};
      const status = isResearchStatus(frontmatter["research-status"])
        ? frontmatter["research-status"]
        : "backlog";
      const id =
        typeof frontmatter["research-id"] === "string"
          ? frontmatter["research-id"]
          : file.path;
      const outputLink =
        typeof frontmatter["research-output"] === "string"
          ? frontmatter["research-output"]
          : undefined;

      const rawPriority = frontmatter["research-priority"];
      const priority: ResearchPriority =
        rawPriority === "high" || rawPriority === "low" ? rawPriority : "normal";

      const rawTags = frontmatter["tags"];
      const allRawTags: string[] = Array.isArray(rawTags)
        ? (rawTags as string[])
        : typeof rawTags === "string" && rawTags
          ? [rawTags as string]
          : [];
      const tags = allRawTags
        .map((t) => String(t).replace(/^#/, ""))
        .filter((t) => t !== "research/idea");

      const content = await this.app.vault.cachedRead(file);

      items.push({
        id,
        title: file.basename,
        status,
        file,
        outputLink,
        questionProgress: this.parser.parseQuestionProgress(content),
        priority,
        tags,
      });
    }

    return items.sort((a, b) => {
      const statusDelta = STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status);
      if (statusDelta !== 0) return statusDelta;
      const priorityDelta = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
      if (priorityDelta !== 0) return priorityDelta;
      return a.title.localeCompare(b.title);
    });
  }

  async attachLatestRuns(items: ResearchItem[], runStore: ResearchRunStore) {
    const summaries = await runStore.latestByNotePath();
    return items.map((item) => ({
      ...item,
      latestRun: summaries.get(item.file.path),
    }));
  }

  async create(title: string, description: string): Promise<TFile> {
    const folder = normalizeFolder(this.plugin.settings.researchFolder);
    await this.ensureFolder(folder);

    const safeTitle = sanitizeFileName(title);
    const path = await this.nextAvailablePath(folder, safeTitle);
    return this.app.vault.create(path, buildResearchNote(safeTitle, description, this.plugin.settings));
  }

  async convertToResearchIdea(file: TFile): Promise<void> {
    const now = nowIso();
    await this.app.fileManager.processFrontMatter(file, (frontmatter) => {
      if (!frontmatter["research-id"]) frontmatter["research-id"] = generateResearchId();
      if (!frontmatter["research-status"]) frontmatter["research-status"] = "backlog";
      if (!frontmatter["research-created"]) frontmatter["research-created"] = now;
      frontmatter["research-updated"] = now;
      this.ensureResearchTag(frontmatter);
    });

    const content = await this.app.vault.read(file);
    if (!/^##\s+Clarifying questions\s*$/im.test(content)) {
      const suffix = content.endsWith("\n") ? "" : "\n";
      await this.app.vault.modify(file, `${content}${suffix}\n## Clarifying questions\n\n## Links\n`);
    }
  }

  async moveStatus(file: TFile, status: ResearchStatus) {
    await this.app.fileManager.processFrontMatter(file, (frontmatter) => {
      frontmatter["research-status"] = status;
      frontmatter["research-updated"] = nowIso();
      if (!frontmatter["research-id"]) frontmatter["research-id"] = generateResearchId();
      this.ensureResearchTag(frontmatter);
    });
  }

  async isResearchFile(file: TFile) {
    const frontmatter = this.app.metadataCache.getFileCache(file)?.frontmatter;
    if (!frontmatter) return false;
    if (frontmatter["research-id"]) return true;

    const tags = frontmatter.tags;
    if (Array.isArray(tags)) return tags.includes("research/idea") || tags.includes("#research/idea");
    return tags === "research/idea" || tags === "#research/idea";
  }

  async insertQuestions(file: TFile, questions: string[]) {
    const content = await this.app.vault.read(file);
    const questionLines = questions.flatMap((question) => [
      `- [ ] ${question}`,
      "  Answer: ",
      "",
    ]);

    const nextContent = this.insertIntoClarifyingQuestions(content, questionLines.join("\n"));
    await this.app.vault.modify(file, nextContent);
    await this.app.fileManager.processFrontMatter(file, (frontmatter) => {
      frontmatter["research-updated"] = nowIso();
      this.ensureResearchTag(frontmatter);
    });
  }

  async readResearchContext(file: TFile) {
    return this.app.vault.cachedRead(file);
  }

  private insertIntoClarifyingQuestions(content: string, insertion: string) {
    const heading = /^##\s+Clarifying questions\s*$/im;
    const match = content.match(heading);

    if (!match || match.index === undefined) {
      const suffix = content.endsWith("\n") ? "" : "\n";
      return `${content}${suffix}\n## Clarifying questions\n\n${insertion}\n`;
    }

    const sectionStart = match.index + match[0].length;
    const before = content.slice(0, sectionStart);
    const after = content.slice(sectionStart);
    const trimmedAfter = after.replace(/^\s*/, "\n\n");
    return `${before}\n\n${insertion}${trimmedAfter}`;
  }

  private ensureResearchTag(frontmatter: Record<string, unknown>) {
    const tags = frontmatter.tags;
    if (Array.isArray(tags)) {
      if (!tags.includes("research/idea")) tags.push("research/idea");
      return;
    }

    if (typeof tags === "string" && tags.trim()) {
      if (tags === "research/idea" || tags === "#research/idea") return;
      frontmatter.tags = [tags, "research/idea"];
      return;
    }

    frontmatter.tags = ["research/idea"];
  }

  private async ensureFolder(folder: string) {
    if (!folder) return;
    const parts = folder.split("/").filter(Boolean);
    let current = "";

    for (const part of parts) {
      current = current ? `${current}/${part}` : part;
      if (!this.app.vault.getAbstractFileByPath(current)) {
        await this.app.vault.createFolder(current);
      }
    }
  }

  private async nextAvailablePath(folder: string, title: string) {
    let suffix = 0;
    while (true) {
      const fileName = suffix === 0 ? `${title}.md` : `${title} ${suffix + 1}.md`;
      const path = normalizePath(folder ? `${folder}/${fileName}` : fileName);
      if (!this.app.vault.getAbstractFileByPath(path)) return path;
      suffix += 1;
    }
  }
}

class ResearchRunStore {
  constructor(
    private readonly app: App,
    private readonly plugin: ResearcherPlugin,
  ) {}

  async startForFile(file: TFile): Promise<ResearchRunRecord> {
    const isResearchFile = await this.plugin.store.isResearchFile(file);
    if (!isResearchFile) throw new Error("The active note is not a research idea.");

    const context = await this.plugin.store.readResearchContext(file);
    const runId = `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const runFolder = normalizePath(
      `${normalizeFolder(this.plugin.settings.runsFolder)}/${slugify(file.basename)}-${runTimestamp()}`,
    );
    await this.ensureFolder(runFolder);

    const reportPath = normalizePath(`${runFolder}/report.md`);
    const now = nowIso();
    const record: ResearchRunRecord = {
      id: runId,
      notePath: file.path,
      noteTitle: file.basename,
      runFolder,
      reportPath,
      createdAt: now,
      updatedAt: now,
      status: "queued",
      progress: {
        step: "queued",
        message: "Queued for deep research.",
        percent: 0,
      },
      request: {
        context,
        llmProvider: this.plugin.settings.llmProvider,
        llmBaseUrl: this.plugin.settings.llmBaseUrl.trim() || (LLM_PROVIDERS[this.plugin.settings.llmProvider]?.baseUrl ?? ""),
        llmModel: this.plugin.settings.llmModel,
      },
    };

    await this.writeRun(record);
    await this.writeStatus(record);
    await this.app.fileManager.processFrontMatter(file, (frontmatter) => {
      frontmatter["research-latest-run"] = `[[${runFolder}/run]]`;
      frontmatter["research-updated"] = nowIso();
    });

    return record;
  }

  async latestByNotePath(): Promise<Map<string, ResearchRunSummary>> {
    const byNote = new Map<string, ResearchRunSummary>();
    const files = this.app.vault
      .getFiles()
      .filter((file) => file.path.startsWith(`${normalizeFolder(this.plugin.settings.runsFolder)}/`))
      .filter((file) => file.name === "run.json");

    for (const file of files) {
      const record = await this.readRunFile(file);
      if (!record) continue;

      const existing = byNote.get(record.notePath);
      if (existing && existing.updatedAt >= record.updatedAt) continue;
      byNote.set(record.notePath, {
        id: record.id,
        status: record.status,
        message: record.progress.message,
        percent: record.progress.percent,
        runFolder: record.runFolder,
        reportPath: record.reportPath,
        updatedAt: record.updatedAt,
      });
    }

    return byNote;
  }

  async writeRun(record: ResearchRunRecord) {
    await this.writeJson(`${record.runFolder}/run.json`, record);
  }

  async writeStatus(record: ResearchRunRecord) {
    await this.writeJson(`${record.runFolder}/status.json`, {
      id: record.id,
      status: record.status,
      progress: record.progress,
      reportPath: record.reportPath,
      updatedAt: record.updatedAt,
    });
  }

  async syncCompletedRunFromFile(file: TFile) {
    const record = await this.readRunFile(file);
    if (record?.status === "completed") await this.linkCompletedRun(record);
  }

  async linkCompletedRun(record: ResearchRunRecord) {
    const file = this.app.vault.getAbstractFileByPath(record.notePath);
    if (!(file instanceof TFile)) return;

    await this.app.fileManager.processFrontMatter(file, (frontmatter) => {
      frontmatter["research-status"] = "completed";
      frontmatter["research-output"] = `[[${record.reportPath.replace(/\.md$/, "")}]]`;
      frontmatter["research-latest-run"] = `[[${record.runFolder}/run]]`;
      frontmatter["research-updated"] = nowIso();
    });
  }

  private async readRunFile(file: TFile): Promise<ResearchRunRecord | null> {
    try {
      return JSON.parse(await this.app.vault.cachedRead(file)) as ResearchRunRecord;
    } catch {
      return null;
    }
  }

  private async writeJson(path: string, value: unknown) {
    const normalizedPath = normalizePath(path);
    const existing = this.app.vault.getAbstractFileByPath(normalizedPath);
    const content = `${JSON.stringify(value, null, 2)}\n`;

    if (existing instanceof TFile) {
      await this.app.vault.modify(existing, content);
      return;
    }

    await this.app.vault.create(normalizedPath, content);
  }

  private async ensureFolder(folder: string) {
    const parts = folder.split("/").filter(Boolean);
    let current = "";

    for (const part of parts) {
      current = current ? `${current}/${part}` : part;
      if (!this.app.vault.getAbstractFileByPath(current)) {
        await this.app.vault.createFolder(current);
      }
    }
  }
}

interface DeepResearchRunner {
  run(record: ResearchRunRecord): Promise<void>;
}

class SidecarDeepResearchRunner implements DeepResearchRunner {
  constructor(
    private readonly app: App,
    private readonly plugin: ResearcherPlugin,
  ) {}

  async run(record: ResearchRunRecord) {
    const vaultBasePath = getVaultBasePath(this.app);
    if (!vaultBasePath) {
      throw new Error("Sidecar deep research requires a desktop filesystem vault.");
    }

    const scriptPath = this.resolveScriptPath(vaultBasePath);
    const runPath = join(vaultBasePath, record.runFolder, "run.json");
    const child = spawn(this.plugin.settings.sidecarCommand || "python3", [
      scriptPath,
      "--vault",
      vaultBasePath,
      "--run",
      runPath,
    ], {
      cwd: vaultBasePath,
      stdio: "ignore",
      detached: true,
      env: {
        ...process.env,
        RESEARCHER_LLM_API_KEY: this.plugin.settings.llmApiKey,
      },
    });

    child.on("error", (error: NodeJS.ErrnoException) => {
      const msg = error.code === "ENOENT"
        ? `Python 3 not found. Install it from python.org or run: brew install python3`
        : `Could not start deep research sidecar: ${error.message}`;
      new Notice(msg);
    });

    child.unref();
  }

  private resolveScriptPath(vaultBasePath: string) {
    const configured = this.plugin.settings.sidecarScriptPath.trim();
    if (configured) {
      return isAbsolute(configured) ? configured : join(vaultBasePath, configured);
    }

    return join(
      vaultBasePath,
      ".obsidian",
      "plugins",
      this.plugin.manifest.id,
      "sidecar",
      "deep_research.py",
    );
  }
}

class ResearchIdeaModal extends Modal {
  private title = "";
  private description = "";

  constructor(
    app: App,
    private readonly initialDescription: string,
    private readonly onSubmit: (title: string, description: string) => Promise<void>,
  ) {
    super(app);
    this.description = initialDescription;
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h2", { text: "Create research idea" });

    new Setting(contentEl).setName("Title").addText((text) => {
      text.setPlaceholder("What do you want to research?");
      text.onChange((value) => {
        this.title = value;
      });
      text.inputEl.focus();
    });

    new Setting(contentEl).setName("Context").addTextArea((text) => {
      text.setPlaceholder("Any useful context, source text, or constraints.");
      text.setValue(this.description);
      text.inputEl.rows = 8;
      text.onChange((value) => {
        this.description = value;
      });
    });

    new Setting(contentEl).addButton((button: ButtonComponent) => {
      button
        .setButtonText("Create")
        .setCta()
        .onClick(async () => {
          if (!this.title.trim()) {
            new Notice("Add a title first.");
            return;
          }
          await this.onSubmit(this.title.trim(), this.description.trim());
          this.close();
        });
    });
  }

  onClose() {
    this.contentEl.empty();
  }
}

class QuestionGenerationModal extends Modal {
  constructor(
    app: App,
    private readonly item: ResearchItem,
    private readonly onGenerate: () => Promise<void>,
    private readonly onSkip: () => Promise<void>,
  ) {
    super(app);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h2", { text: "Move to Refine" });
    contentEl.createEl("p", {
      text: `Generate clarifying questions for "${this.item.title}"? The LLM will review the note and suggest what it needs to know before researching.`,
      cls: "researcher-modal__desc",
    });

    new Setting(contentEl)
      .addButton((btn) =>
        btn.setButtonText("Generate questions").setCta().onClick(async () => {
          this.close();
          await this.onGenerate();
        }),
      )
      .addButton((btn) =>
        btn.setButtonText("Skip to Research →").onClick(async () => {
          this.close();
          await this.onSkip();
        }),
      )
      .addButton((btn) =>
        btn.setButtonText("Cancel").onClick(() => this.close()),
      );
  }

  onClose() {
    this.contentEl.empty();
  }
}

class StartDeepResearchModal extends Modal {
  constructor(
    app: App,
    private readonly item: ResearchItem,
    private readonly onStart: () => Promise<void>,
  ) {
    super(app);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h2", { text: "Start Deep Research" });

    const { answered, total } = this.item.questionProgress;
    if (total > 0) {
      const rowEl = contentEl.createDiv({ cls: "researcher-modal__progress-row" });
      const pct = total > 0 ? Math.round((answered / total) * 100) : 0;
      rowEl.createSpan({ text: `${answered}/${total} questions answered` });
      const barWrap = rowEl.createDiv({ cls: "researcher-modal__progress-bar-wrap" });
      barWrap.createDiv({
        cls: "researcher-modal__progress-bar-fill",
        attr: { style: `width: ${pct}%` },
      });
    }

    contentEl.createEl("p", {
      text: `The LLM will research "${this.item.title}" and write a report. This runs in the background using your configured LLM provider.`,
      cls: "researcher-modal__desc",
    });

    new Setting(contentEl)
      .addButton((btn) =>
        btn.setButtonText("Start research").setCta().onClick(async () => {
          this.close();
          await this.onStart();
        }),
      )
      .addButton((btn) =>
        btn.setButtonText("Cancel").onClick(() => this.close()),
      );
  }

  onClose() {
    this.contentEl.empty();
  }
}

class ConfirmDeleteModal extends Modal {
  constructor(
    app: App,
    private readonly item: ResearchItem,
    private readonly onConfirm: () => Promise<void>,
  ) {
    super(app);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h2", { text: "Delete research idea" });
    contentEl.createEl("p", {
      text: `Delete "${this.item.title}"? This permanently deletes the note.`,
      cls: "researcher-modal__desc",
    });

    new Setting(contentEl)
      .addButton((btn) =>
        btn.setButtonText("Delete").setWarning().onClick(async () => {
          this.close();
          await this.onConfirm();
        }),
      )
      .addButton((btn) =>
        btn.setButtonText("Cancel").onClick(() => this.close()),
      );
  }

  onClose() {
    this.contentEl.empty();
  }
}

const ACTIVE_RUN_STATUSES = new Set<ResearchRunStatus>(["queued", "planning", "searching", "fetching", "synthesizing"]);

const DROP_TARGETS: Partial<Record<ResearchStatus, ResearchStatus>> = {
  "to-refine": "backlog",
  "to-research": "to-refine",
};
const DRAG_SOURCES = new Set<ResearchStatus>(["backlog", "to-refine"]);

class ResearcherView extends ItemView {
  private draggedItem: ResearchItem | null = null;
  private isDragging = false;
  private dragPlaceholder: HTMLElement | null = null;
  private filterText = "";
  private filterTag: string | null = null;
  private collapsedGroups = new Set<ResearchStatus>();
  private bodyEl: HTMLElement | null = null;
  private cachedItems: ResearchItem[] = [];

  constructor(
    leaf: WorkspaceLeaf,
    private readonly plugin: ResearcherPlugin,
  ) {
    super(leaf);
  }

  getViewType() {
    return VIEW_TYPE_RESEARCHER;
  }

  getDisplayText() {
    return "Researcher";
  }

  getIcon() {
    return "search";
  }

  async onOpen() {
    await this.render();
  }

  async render() {
    if (this.isDragging) return;

    const allItems = await this.plugin.store.attachLatestRuns(
      await this.plugin.store.list(),
      this.plugin.runStore,
    );

    // Collect all unique tags across every research item (excluding always-present research/idea)
    const allTagsSet = new Set<string>();
    for (const item of allItems) {
      for (const tag of item.tags) allTagsSet.add(tag);
    }
    const allTags = [...allTagsSet].sort();

    this.cachedItems = allItems;

    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("researcher-view");

    // ── Header ────────────────────────────────────────────────────────────────
    const headerEl = contentEl.createDiv({ cls: "researcher-view__header" });
    headerEl.createDiv({ cls: "researcher-view__title", text: "Researcher" });
    const createButton = headerEl.createEl("button", {
      cls: "researcher-view__create",
      text: "+ New",
    });
    createButton.addEventListener("click", () => this.plugin.openCreateModal(""));

    // ── Filter bar ────────────────────────────────────────────────────────────
    const filterEl = contentEl.createDiv({ cls: "researcher-view__filter" });
    const searchInput = filterEl.createEl("input", {
      cls: "researcher-view__search",
      attr: { type: "text", placeholder: "Search ideas…" },
    });
    searchInput.value = this.filterText;
    searchInput.addEventListener("input", () => {
      this.filterText = searchInput.value;
      this.renderBody();
    });

    if (allTags.length > 0) {
      const tagRowEl = filterEl.createDiv({ cls: "researcher-view__tag-filter" });
      for (const tag of allTags) {
        const isActive = this.filterTag === tag;
        const chipEl = tagRowEl.createEl("button", {
          cls: `researcher-view__tag-chip${isActive ? " researcher-view__tag-chip--active" : ""}`,
          text: `#${tag}`,
        });
        chipEl.addEventListener("click", () => {
          this.filterTag = isActive ? null : tag;
          void this.render();
        });
      }
    }

    this.bodyEl = contentEl.createDiv({ cls: "researcher-view__content" });
    this.renderBody();
  }

  private renderBody() {
    const bodyEl = this.bodyEl;
    if (!bodyEl) return;
    bodyEl.empty();

    let visibleItems = this.cachedItems;
    if (this.filterText.trim()) {
      const query = this.filterText.toLowerCase();
      visibleItems = visibleItems.filter((item) => item.title.toLowerCase().includes(query));
    }
    if (this.filterTag) {
      const tag = this.filterTag;
      visibleItems = visibleItems.filter((item) => item.tags.includes(tag));
    }

    for (const status of STATUS_ORDER) {
      const groupItems = visibleItems.filter((item) => item.status === status);
      const isCollapsed = this.collapsedGroups.has(status);
      const groupEl = bodyEl.createDiv({ cls: "researcher-view__group" });

      const acceptsFrom = DROP_TARGETS[status];
      if (acceptsFrom && !isCollapsed) {
        groupEl.addEventListener("dragover", (e) => {
          if (this.draggedItem?.status !== acceptsFrom) return;
          e.preventDefault();
          e.dataTransfer!.dropEffect = "move";
          if (!groupEl.hasClass("researcher-view__group--drag-over")) {
            groupEl.addClass("researcher-view__group--drag-over");
            this.dragPlaceholder?.remove();
            this.dragPlaceholder = groupEl.createEl("div", {
              cls: "researcher-card researcher-card--placeholder",
            });
          }
        });
        groupEl.addEventListener("dragleave", (e) => {
          if (groupEl.contains(e.relatedTarget as Node)) return;
          groupEl.removeClass("researcher-view__group--drag-over");
          this.dragPlaceholder?.remove();
          this.dragPlaceholder = null;
        });
        groupEl.addEventListener("drop", (e) => {
          e.preventDefault();
          groupEl.removeClass("researcher-view__group--drag-over");
          this.dragPlaceholder?.remove();
          this.dragPlaceholder = null;
          const item = this.draggedItem;
          if (!item || item.status !== acceptsFrom) return;
          this.draggedItem = null;
          void this.handleDrop(item, status);
        });
      }

      const groupHeaderEl = groupEl.createDiv({ cls: "researcher-view__group-header" });
      groupHeaderEl.createSpan({ text: STATUS_LABELS[status] });
      groupHeaderEl.createSpan({ cls: "researcher-view__group-count", text: String(groupItems.length) });
      groupHeaderEl.createSpan({
        cls: `researcher-view__group-chevron${isCollapsed ? " researcher-view__group-chevron--collapsed" : ""}`,
      });
      groupHeaderEl.addEventListener("click", () => {
        if (this.collapsedGroups.has(status)) {
          this.collapsedGroups.delete(status);
        } else {
          this.collapsedGroups.add(status);
        }
        this.renderBody();
      });

      if (isCollapsed) continue;

      if (groupItems.length === 0) {
        const isFiltered = Boolean(this.filterText.trim() || this.filterTag);
        const emptyText = acceptsFrom && !isFiltered ? "Drop here" : isFiltered ? "No matches" : "Empty";
        groupEl.createDiv({ cls: "researcher-view__empty", text: emptyText });
        continue;
      }

      for (const item of groupItems) {
        const cardEl = groupEl.createEl("div", {
          cls: "researcher-card",
          attr: { role: "button", tabindex: "0" },
        });

        if (DRAG_SOURCES.has(item.status)) {
          cardEl.draggable = true;
          cardEl.addEventListener("dragstart", (e) => {
            this.isDragging = true;
            this.draggedItem = item;
            if (e.dataTransfer) {
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData("text/plain", item.id);
            }
            window.setTimeout(() => {
              cardEl.addClass("researcher-card--dragging");
              bodyEl.querySelectorAll<HTMLElement>(".researcher-view__group").forEach((g) => {
                const s = g.dataset["status"] as ResearchStatus | undefined;
                if (s && DROP_TARGETS[s] === item.status) g.addClass("researcher-view__group--droppable");
              });
            }, 0);
          });
          cardEl.addEventListener("dragend", () => {
            this.isDragging = false;
            this.draggedItem = null;
            cardEl.removeClass("researcher-card--dragging");
            this.dragPlaceholder?.remove();
            this.dragPlaceholder = null;
            bodyEl.querySelectorAll<HTMLElement>(".researcher-view__group").forEach((g) => {
              g.removeClass("researcher-view__group--droppable");
              g.removeClass("researcher-view__group--drag-over");
            });
          });
        }

        groupEl.dataset["status"] = status;

        const cardHeaderEl = cardEl.createDiv({ cls: "researcher-card__header" });
        cardHeaderEl.createDiv({ cls: "researcher-card__title", text: item.title });
        if (item.priority !== "normal") {
          cardHeaderEl.createSpan({
            cls: `researcher-card__priority researcher-card__priority--${item.priority}`,
            text: item.priority,
          });
        }

        const { answered, total } = item.questionProgress;
        const hasQuestions = total > 0;
        const hasOutput = Boolean(item.outputLink);

        if (hasQuestions || hasOutput) {
          const metaEl = cardEl.createDiv({ cls: "researcher-card__meta" });
          if (hasQuestions) {
            metaEl.createSpan({
              cls: "researcher-card__chip",
              text: `${answered}/${total} answered`,
            });
          }
          if (hasOutput) {
            const reportChip = metaEl.createDiv({
              cls: "researcher-card__chip researcher-card__chip--done researcher-card__chip--actionable",
              text: "Report ready →",
              attr: { role: "button" },
            });
            const reportLinkPath = extractWikilinkPath(item.outputLink ?? "");
            if (reportLinkPath) {
              reportChip.addEventListener("click", (e) => {
                e.stopPropagation();
                const reportFile = this.plugin.app.metadataCache.getFirstLinkpathDest(
                  reportLinkPath,
                  item.file.path,
                );
                if (reportFile) void this.plugin.app.workspace.getLeaf(false).openFile(reportFile);
              });
            }
          }
        }

        if (item.latestRun && item.latestRun.status !== "completed") {
          const isFailed = item.latestRun.status === "failed";
          const isActive = ACTIVE_RUN_STATUSES.has(item.latestRun.status);
          const runEl = cardEl.createDiv({ cls: "researcher-card__run" });

          if (!isFailed) {
            const progressEl = runEl.createDiv({ cls: "researcher-card__progress" });
            progressEl.createDiv({
              cls: "researcher-card__progress-bar",
              attr: { style: `width: ${item.latestRun.percent}%` },
            });
          }

          const statusEl = runEl.createDiv({ cls: "researcher-card__run-status" });
          const dotCls = isFailed
            ? "researcher-card__run-dot researcher-card__run-dot--failed"
            : isActive
              ? "researcher-card__run-dot researcher-card__run-dot--active"
              : "researcher-card__run-dot";
          statusEl.createDiv({ cls: dotCls });
          statusEl.createSpan({
            text: isFailed
              ? `Failed · ${item.latestRun.message}`
              : `${formatRunStatus(item.latestRun.status)} · ${item.latestRun.percent}%`,
          });

          if (!isFailed && item.latestRun.message) {
            runEl.createDiv({
              cls: "researcher-card__run-message",
              text: item.latestRun.message,
            });
          }

          if (isFailed) {
            const retryEl = runEl.createDiv({
              cls: "researcher-card__retry",
              text: "Retry",
              attr: { role: "button" },
            });
            retryEl.addEventListener("click", (e) => {
              e.stopPropagation();
              void this.plugin.startDeepResearchForFile(item.file);
            });
          }
        }

        cardEl.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          this.openCardMenu(item, e);
        });

        cardEl.addEventListener("click", () => {
          if (this.isDragging) return;
          void this.plugin.app.workspace.getLeaf(false).openFile(item.file);
        });

        cardEl.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            if (this.isDragging) return;
            void this.plugin.app.workspace.getLeaf(false).openFile(item.file);
          }
        });
      }
    }
  }

  private openCardMenu(item: ResearchItem, event: MouseEvent) {
    const menu = new Menu();

    menu.addItem((i) =>
      i.setTitle("Open note").setIcon("file-text").onClick(() => {
        void this.plugin.app.workspace.getLeaf(false).openFile(item.file);
      }),
    );

    menu.addSeparator();

    if (item.status === "backlog") {
      menu.addItem((i) =>
        i.setTitle("Move to Refine →").setIcon("arrow-right").onClick(() => {
          new QuestionGenerationModal(
            this.app, item,
            async () => {
              await this.plugin.store.moveStatus(item.file, "to-refine");
              await this.plugin.refreshViews();
              await this.plugin.queue.generateQuestionsForFile(item.file);
            },
            async () => {
              await this.plugin.store.moveStatus(item.file, "to-research");
              await this.plugin.refreshViews();
            },
          ).open();
        }),
      );
    }

    if (item.status === "to-refine") {
      menu.addItem((i) =>
        i.setTitle("Move to Research →").setIcon("arrow-right").onClick(() => {
          new StartDeepResearchModal(this.app, item, async () => {
            await this.plugin.startDeepResearchForFile(item.file);
          }).open();
        }),
      );
    }

    if (item.status === "to-research") {
      menu.addItem((i) =>
        i.setTitle("Start deep research →").setIcon("play").onClick(() => {
          new StartDeepResearchModal(this.app, item, async () => {
            await this.plugin.startDeepResearchForFile(item.file);
          }).open();
        }),
      );
    }

    const reportLinkPath = item.outputLink ? extractWikilinkPath(item.outputLink) : null;
    if (reportLinkPath) {
      menu.addItem((i) =>
        i.setTitle("Open report").setIcon("book-open").onClick(() => {
          const reportFile = this.plugin.app.metadataCache.getFirstLinkpathDest(
            reportLinkPath,
            item.file.path,
          );
          if (reportFile) void this.plugin.app.workspace.getLeaf(false).openFile(reportFile);
        }),
      );
    }

    if (item.status === "to-refine") {
      menu.addItem((i) =>
        i.setTitle("← Send back to Backlog").setIcon("arrow-left").onClick(async () => {
          await this.plugin.store.moveStatus(item.file, "backlog");
          await this.plugin.refreshViews();
        }),
      );
    }

    if (item.status === "to-research") {
      menu.addItem((i) =>
        i.setTitle("← Send back to Refine").setIcon("arrow-left").onClick(async () => {
          await this.plugin.store.moveStatus(item.file, "to-refine");
          await this.plugin.refreshViews();
        }),
      );
    }

    if (item.status === "researching") {
      menu.addItem((i) =>
        i.setTitle("← Reset to To Research").setIcon("rotate-ccw").onClick(async () => {
          await this.plugin.store.moveStatus(item.file, "to-research");
          await this.plugin.refreshViews();
        }),
      );
    }

    if (item.status === "completed") {
      menu.addItem((i) =>
        i.setTitle("← Reopen").setIcon("rotate-ccw").onClick(async () => {
          await this.plugin.store.moveStatus(item.file, "to-research");
          await this.plugin.refreshViews();
        }),
      );
    }

    if (item.status !== "completed") {
      menu.addSeparator();
      menu.addItem((i) =>
        i.setTitle("Mark as done").setIcon("check").onClick(async () => {
          await this.plugin.store.moveStatus(item.file, "completed");
          await this.plugin.refreshViews();
        }),
      );
    }

    menu.addSeparator();

    menu.addItem((i) =>
      i.setTitle("Delete idea").setIcon("trash").onClick(() => {
        new ConfirmDeleteModal(this.app, item, async () => {
          await this.plugin.app.vault.delete(item.file);
          await this.plugin.refreshViews();
        }).open();
      }),
    );

    menu.showAtMouseEvent(event);
  }

  private async handleDrop(item: ResearchItem, targetStatus: ResearchStatus) {
    if (targetStatus === "to-refine") {
      new QuestionGenerationModal(
        this.app,
        item,
        async () => {
          await this.plugin.store.moveStatus(item.file, "to-refine");
          await this.plugin.refreshViews();
          await this.plugin.queue.generateQuestionsForFile(item.file);
        },
        async () => {
          await this.plugin.store.moveStatus(item.file, "to-research");
          await this.plugin.refreshViews();
        },
      ).open();
      return;
    }

    if (targetStatus === "to-research") {
      new StartDeepResearchModal(
        this.app,
        item,
        async () => {
          await this.plugin.startDeepResearchForFile(item.file);
        },
      ).open();
    }
  }
}

function formatRunStatus(status: ResearchRunStatus) {
  const s = status.replaceAll("-", " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function extractWikilinkPath(link: string): string | null {
  const match = link.match(/\[\[(.+?)(?:\|.+?)?\]\]/);
  return match ? match[1] : null;
}

class ResearcherSettingTab extends PluginSettingTab {
  constructor(
    app: App,
    private readonly plugin: ResearcherPlugin,
  ) {
    super(app, plugin);
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Researcher" });

    // ── LLM ──────────────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "LLM provider" });

    const currentMeta = LLM_PROVIDERS[this.plugin.settings.llmProvider];

    new Setting(containerEl)
      .setName("Provider")
      .setDesc("Used for question generation and deep research.")
      .addDropdown((dropdown) => {
        for (const [kind, meta] of Object.entries(LLM_PROVIDERS)) {
          dropdown.addOption(kind, meta.label);
        }
        dropdown.setValue(this.plugin.settings.llmProvider).onChange(async (value) => {
          this.plugin.settings.llmProvider = value as LlmProviderKind;
          this.plugin.settings.llmBaseUrl = "";
          await this.plugin.saveSettings();
          this.display();
        });
      });

    const apiKeyMeta = LLM_PROVIDERS[this.plugin.settings.llmProvider];
    if (this.plugin.settings.llmProvider !== "ollama") {
      const keyDesc = document.createDocumentFragment();
      if (apiKeyMeta.keyUrl) {
        keyDesc.append("Get your key at ");
        keyDesc.createEl("a", { text: apiKeyMeta.keyUrl, href: apiKeyMeta.keyUrl });
      } else {
        keyDesc.append("API key for this provider.");
      }
      new Setting(containerEl)
        .setName("API key")
        .setDesc(keyDesc)
        .addText((text) => {
          text.inputEl.type = "password";
          text.setPlaceholder(apiKeyMeta.keyPlaceholder);
          text.setValue(this.plugin.settings.llmApiKey).onChange(async (value) => {
            this.plugin.settings.llmApiKey = value;
            await this.plugin.saveSettings();
          });
        });
    }

    new Setting(containerEl)
      .setName("Model")
      .setDesc("Leave empty to use placeholder questions without LLM.")
      .addText((text) =>
        text
          .setPlaceholder(currentMeta.modelPlaceholder)
          .setValue(this.plugin.settings.llmModel)
          .onChange(async (value) => {
            this.plugin.settings.llmModel = value;
            await this.plugin.saveSettings();
          }),
      );

    if (this.plugin.settings.llmProvider === "ollama" || this.plugin.settings.llmProvider === "openai_compat") {
      new Setting(containerEl)
        .setName("Base URL")
        .setDesc(
          this.plugin.settings.llmProvider === "ollama"
            ? "Ollama server root. A trailing /v1 is tolerated."
            : "Base URL for the OpenAI-compatible endpoint.",
        )
        .addText((text) =>
          text
            .setPlaceholder(LLM_PROVIDERS[this.plugin.settings.llmProvider].baseUrl || "https://…/v1")
            .setValue(this.plugin.settings.llmBaseUrl)
            .onChange(async (value) => {
              this.plugin.settings.llmBaseUrl = value;
              await this.plugin.saveSettings();
            }),
        );
    }

    // ── Folders ───────────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "Folders" });

    new Setting(containerEl)
      .setName("Research ideas")
      .setDesc("Where new research idea notes are created.")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.researchFolder)
          .setValue(this.plugin.settings.researchFolder)
          .onChange(async (value) => {
            this.plugin.settings.researchFolder = value || DEFAULT_SETTINGS.researchFolder;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Research runs")
      .setDesc("Where deep research run state and reports are stored.")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.runsFolder)
          .setValue(this.plugin.settings.runsFolder)
          .onChange(async (value) => {
            this.plugin.settings.runsFolder = value || DEFAULT_SETTINGS.runsFolder;
            await this.plugin.saveSettings();
          }),
      );

    // ── Advanced ──────────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "Advanced" });

    new Setting(containerEl)
      .setName("Python command")
      .setDesc("Executable used to run the research sidecar script.")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.sidecarCommand)
          .setValue(this.plugin.settings.sidecarCommand)
          .onChange(async (value) => {
            this.plugin.settings.sidecarCommand = value || DEFAULT_SETTINGS.sidecarCommand;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Sidecar script path")
      .setDesc("Leave empty to use the bundled script. Accepts absolute or vault-relative paths.")
      .addText((text) =>
        text
          .setPlaceholder(".obsidian/plugins/researcher/sidecar/deep_research.py")
          .setValue(this.plugin.settings.sidecarScriptPath)
          .onChange(async (value) => {
            this.plugin.settings.sidecarScriptPath = value;
            await this.plugin.saveSettings();
          }),
      );
  }
}

export default class ResearcherPlugin extends Plugin {
  settings: ResearcherSettings = DEFAULT_SETTINGS;
  store: ResearchStore = new ResearchStore(this.app, this);
  runStore: ResearchRunStore = new ResearchRunStore(this.app, this);
  deepResearchRunner: DeepResearchRunner = new SidecarDeepResearchRunner(this.app, this);
  queue: ResearchQueue = new ResearchQueue(this, new ResearchQuestionProvider(this.settings));
  private ribbonEl: HTMLElement | null = null;

  async onload() {
    await this.loadSettings();

    this.store = new ResearchStore(this.app, this);
    this.runStore = new ResearchRunStore(this.app, this);
    this.deepResearchRunner = new SidecarDeepResearchRunner(this.app, this);
    this.queue = new ResearchQueue(this, new ResearchQuestionProvider(this.settings));

    this.registerView(
      VIEW_TYPE_RESEARCHER,
      (leaf) => new ResearcherView(leaf, this),
    );

    this.ribbonEl = this.addRibbonIcon("search", "Open Researcher", () => {
      void this.activateView();
    });

    this.addCommand({
      id: "create-research-idea",
      name: "Create research idea",
      callback: () => this.openCreateModal(""),
    });

    this.addCommand({
      id: "make-current-note-research-idea",
      name: "Make current note a research idea",
      callback: () => {
        void this.makeCurrentNoteResearchIdea();
      },
    });

    this.addCommand({
      id: "capture-selection-as-research-idea",
      name: "Capture selection as research idea",
      editorCallback: (editor: Editor) => {
        this.openCreateModal(editor.getSelection());
      },
    });

    this.addCommand({
      id: "move-research-idea-to-refinement",
      name: "Move research idea to refinement",
      callback: () => {
        void this.moveActiveFileToStatus("to-refine");
      },
    });

    this.addCommand({
      id: "mark-research-idea-ready-for-research",
      name: "Mark research idea ready for research",
      callback: () => {
        void this.moveActiveFileToStatus("to-research");
      },
    });

    this.addCommand({
      id: "generate-clarifying-questions",
      name: "Generate clarifying questions",
      callback: () => {
        void this.queue.generateQuestionsForActiveNote();
      },
    });

    this.addCommand({
      id: "start-deep-research",
      name: "Start deep research on active note",
      callback: () => {
        void this.startDeepResearchForActiveNote();
      },
    });

    this.addCommand({
      id: "open-research-sidebar",
      name: "Open research sidebar",
      callback: () => {
        void this.activateView();
      },
    });

    this.addSettingTab(new ResearcherSettingTab(this.app, this));

    this.registerEvent(this.app.metadataCache.on("changed", () => this.refreshViews()));
    this.registerEvent(this.app.vault.on("create", (file) => this.refreshIfMarkdown(file)));
    this.registerEvent(this.app.vault.on("delete", (file) => this.refreshIfMarkdown(file)));
    this.registerEvent(this.app.vault.on("modify", (file) => this.refreshIfRunFile(file)));
    this.registerEvent(this.app.vault.on("rename", (file) => this.refreshIfMarkdown(file)));
    this.registerInterval(window.setInterval(() => {
      if (this.hasResearchingNotes()) void this.refreshViews();
    }, 5000));

    this.app.workspace.onLayoutReady(() => {
      void this.reconcileStuckRuns().then(() => this.updateRibbonBadge());
    });
  }

  onunload() {
    this.app.workspace.detachLeavesOfType(VIEW_TYPE_RESEARCHER);
  }

  async loadSettings() {
    const loaded = {
      ...DEFAULT_SETTINGS,
      ...(await this.loadData()),
    };
    this.settings = {
      ...loaded,
      llmProvider: isLlmProviderKind(loaded.llmProvider)
        ? loaded.llmProvider
        : DEFAULT_SETTINGS.llmProvider,
    };
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  getActiveMarkdownFile() {
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);
    return view?.file ?? null;
  }

  openCreateModal(initialDescription: string) {
    new ResearchIdeaModal(this.app, initialDescription, async (title, description) => {
      const file = await this.store.create(title, description);
      await this.app.workspace.getLeaf(false).openFile(file);
      await this.refreshViews();
    }).open();
  }

  async makeCurrentNoteResearchIdea() {
    const file = this.getActiveMarkdownFile();
    if (!file) {
      new Notice("Open a note first.");
      return;
    }

    if (await this.store.isResearchFile(file)) {
      new Notice("This note is already a research idea.");
      return;
    }

    await this.store.convertToResearchIdea(file);
    await this.refreshViews();
    new Notice("Note added to research ideas.");
  }

  async activateView() {
    const leaves = this.app.workspace.getLeavesOfType(VIEW_TYPE_RESEARCHER);
    const leaf = leaves[0] ?? this.app.workspace.getRightLeaf(false);
    if (!leaf) return;

    await leaf.setViewState({ type: VIEW_TYPE_RESEARCHER, active: true });
    this.app.workspace.revealLeaf(leaf);
  }

  async moveActiveFileToStatus(status: ResearchStatus) {
    const file = this.getActiveMarkdownFile();
    if (!file) {
      new Notice("Open a research note first.");
      return;
    }

    if (!(await this.store.isResearchFile(file))) {
      new Notice("The active note is not a research idea.");
      return;
    }

    await this.store.moveStatus(file, status);
    await this.refreshViews();
    new Notice(`Moved research idea to ${STATUS_LABELS[status]}.`);
  }

  async startDeepResearchForFile(file: TFile) {
    try {
      const record = await this.runStore.startForFile(file);
      await this.store.moveStatus(file, "researching");
      await this.refreshViews();
      new Notice("Started deep research run.");
      void this.deepResearchRunner.run(record)
        .then(() => this.refreshViews())
        .catch((error: unknown) => {
          new Notice(`Deep research runner failed: ${(error as Error).message}`);
        });
    } catch (error) {
      new Notice(`Could not start deep research: ${(error as Error).message}`);
    }
  }

  async startDeepResearchForActiveNote() {
    const file = this.getActiveMarkdownFile();
    if (!file) {
      new Notice("Open a research note first.");
      return;
    }
    await this.startDeepResearchForFile(file);
  }

  hasResearchingNotes(): boolean {
    return this.app.vault.getMarkdownFiles().some((file) => {
      const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
      return fm?.["research-status"] === "researching";
    });
  }

  private async reconcileStuckRuns() {
    const stuck = this.app.vault.getMarkdownFiles().filter((file) => {
      const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
      return fm?.["research-status"] === "researching";
    });

    if (stuck.length === 0) return;

    const summaries = await this.runStore.latestByNotePath();
    let changed = false;

    for (const file of stuck) {
      const summary = summaries.get(file.path);

      if (!summary || summary.status === "failed") {
        await this.store.moveStatus(file, "to-research");
        changed = true;
      } else if (summary.status === "completed") {
        const runFile = this.app.vault.getAbstractFileByPath(`${summary.runFolder}/run.json`);
        if (runFile instanceof TFile) {
          await this.runStore.syncCompletedRunFromFile(runFile);
          changed = true;
        }
      }
      // Active statuses: leave as-is — the sidecar is still running.
    }

    if (changed) await this.refreshViews();
  }

  async refreshViews() {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE_RESEARCHER)) {
      const view = leaf.view;
      if (view instanceof ResearcherView) await view.render();
    }
    this.updateRibbonBadge();
  }

  updateRibbonBadge() {
    if (!this.ribbonEl) return;
    const activeCount = this.app.vault.getMarkdownFiles().filter((file) => {
      const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
      return fm?.["research-status"] === "researching";
    }).length;

    let badge = this.ribbonEl.querySelector<HTMLElement>(".researcher-ribbon-badge");
    if (activeCount === 0) {
      badge?.remove();
      return;
    }
    if (!badge) {
      badge = this.ribbonEl.createDiv({ cls: "researcher-ribbon-badge" });
    }
    badge.setText(String(activeCount));
  }

  private refreshIfMarkdown(file: TAbstractFile) {
    if (file instanceof TFile && file.extension === "md") {
      void this.refreshViews();
    }
  }

  private refreshIfRunFile(file: TAbstractFile) {
    if (file instanceof TFile && file.path.endsWith("/run.json")) {
      void this.runStore.syncCompletedRunFromFile(file);
      void this.refreshViews();
    }
  }
}
