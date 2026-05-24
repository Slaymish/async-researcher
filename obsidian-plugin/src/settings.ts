import { App, PluginSettingTab, Setting } from "obsidian";
import type AiOsPlugin from "./main";
import { SetupModal, getVaultPath } from "./setup";

export type LlmProvider = "ollama" | "openai" | "anthropic" | "openrouter" | "custom";

export interface AiOsSettings {
  backendUrl: string;
  researchOutputFolder: string;
  surfacingEnabled: boolean;
  surfaceDebounceMs: number;
  surfaceTopK: number;
  surfaceMinScore: number;
  researchK: number;
  researchMaxRepairAttempts: number;
  researchDecompose: "auto" | "always" | "never";
  researchShowDebug: boolean;
  researchSidebarOpen: boolean;
  // Provider settings
  provider: LlmProvider;
  providerApiKey: string;
  providerBaseUrl: string;
  synthesisModel: string;
  judgeModel: string;
}

export const DEFAULT_SETTINGS: AiOsSettings = {
  backendUrl: "http://127.0.0.1:8765",
  researchOutputFolder: "Research Reports",
  surfacingEnabled: true,
  surfaceDebounceMs: 800,
  surfaceTopK: 8,
  surfaceMinScore: 0,
  researchK: 20,
  researchMaxRepairAttempts: 2,
  researchDecompose: "auto",
  researchShowDebug: false,
  researchSidebarOpen: true,
  provider: "ollama",
  providerApiKey: "",
  providerBaseUrl: "",
  synthesisModel: "",
  judgeModel: "",
};

interface ProviderMeta {
  label: string;
  fixedBaseUrl?: string;
  defaultBaseUrl?: string;
  defaultSynthesisModel: string;
  defaultJudgeModel: string;
  requiresApiKey: boolean;
  apiKeyUrl?: string;
  apiKeyLabel?: string;
  note?: string;
}

export const PROVIDER_META: Record<LlmProvider, ProviderMeta> = {
  ollama: {
    label: "Ollama (local)",
    defaultBaseUrl: "http://localhost:11434/v1",
    defaultSynthesisModel: "qwen2.5:14b",
    defaultJudgeModel: "qwen2.5:7b",
    requiresApiKey: false,
  },
  openai: {
    label: "OpenAI",
    fixedBaseUrl: "https://api.openai.com/v1",
    defaultSynthesisModel: "gpt-4o",
    defaultJudgeModel: "gpt-4o-mini",
    requiresApiKey: true,
    apiKeyUrl: "https://platform.openai.com/api-keys",
    apiKeyLabel: "platform.openai.com/api-keys",
  },
  anthropic: {
    label: "Anthropic",
    fixedBaseUrl: "https://api.anthropic.com/v1",
    defaultSynthesisModel: "claude-sonnet-4-6",
    defaultJudgeModel: "claude-haiku-4-5-20251001",
    requiresApiKey: true,
    apiKeyUrl: "https://console.anthropic.com/settings/keys",
    apiKeyLabel: "console.anthropic.com/settings/keys",
    note: "Requires Anthropic's OpenAI-compatible API. Alternatively, access Claude via OpenRouter.",
  },
  openrouter: {
    label: "OpenRouter",
    fixedBaseUrl: "https://openrouter.ai/api/v1",
    defaultSynthesisModel: "anthropic/claude-sonnet-4-5",
    defaultJudgeModel: "anthropic/claude-haiku-4-5",
    requiresApiKey: true,
    apiKeyUrl: "https://openrouter.ai/keys",
    apiKeyLabel: "openrouter.ai/keys",
    note: "Access 200+ models including OpenAI, Anthropic, Meta, and more.",
  },
  custom: {
    label: "Custom (OpenAI-compatible)",
    defaultBaseUrl: "",
    defaultSynthesisModel: "",
    defaultJudgeModel: "",
    requiresApiKey: false,
    note: "Any server exposing the OpenAI /v1/chat/completions API (e.g. LM Studio, llama-swap, vLLM).",
  },
};

export class AiOsSettingTab extends PluginSettingTab {
  constructor(
    app: App,
    private readonly plugin: AiOsPlugin,
  ) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Researcher" });

    // ── Connection ───────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "Connection" });

    new Setting(containerEl)
      .setName("Setup guide")
      .setDesc(
        "First time? The plugin requires a local Python backend. " +
        "Open the guide for step-by-step installation instructions.",
      )
      .addButton((btn) =>
        btn.setButtonText("Open setup guide").onClick(() => {
          new SetupModal(this.app).open();
        }),
      );

    new Setting(containerEl)
      .setName("Your vault path")
      .setDesc(
        "Copy this into the [vault] path setting in config.toml when running ai-os setup.",
      )
      .addText((text) => {
        text.setValue(getVaultPath(this.app));
        text.inputEl.readOnly = true;
        text.inputEl.style.width = "100%";
        text.inputEl.style.fontFamily = "monospace";
        text.inputEl.style.fontSize = "0.85em";
        text.inputEl.style.cursor = "text";
        text.inputEl.style.userSelect = "text";
      });

    new Setting(containerEl)
      .setName("Backend URL")
      .setDesc("URL of the local backend. Defaults to localhost:8765.")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.backendUrl)
          .setValue(this.plugin.settings.backendUrl)
          .onChange(async (value) => {
            this.plugin.settings.backendUrl = value.trim() || DEFAULT_SETTINGS.backendUrl;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Check connection")
      .setDesc("Test the connection to your local backend.")
      .addButton((btn) =>
        btn
          .setButtonText("Check")
          .onClick(async () => {
            await this.plugin.checkHealth();
          }),
      );

    // ── LLM Provider ─────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "LLM Provider" });

    containerEl.createEl("p", {
      text: "Choose which LLM provider handles research and synthesis. Embeddings always run locally via the backend's configured model.",
      cls: "setting-item-description",
    });

    const providerSetting = new Setting(containerEl)
      .setName("Provider")
      .setDesc("The LLM provider to use for research synthesis.")
      .addDropdown((dd) => {
        for (const [value, meta] of Object.entries(PROVIDER_META)) {
          dd.addOption(value, meta.label);
        }
        dd.setValue(this.plugin.settings.provider);
        dd.onChange(async (value) => {
          this.plugin.settings.provider = value as LlmProvider;
          // Clear models so placeholders reflect new provider defaults
          this.plugin.settings.synthesisModel = "";
          this.plugin.settings.judgeModel = "";
          await this.plugin.saveSettings();
          this.display();
        });
      });

    const provider = this.plugin.settings.provider;
    const meta = PROVIDER_META[provider];

    if (meta.note) {
      containerEl.createEl("p", {
        text: meta.note,
        cls: "setting-item-description ai-os-provider-note",
      });
    }

    // API key (cloud providers)
    if (meta.requiresApiKey) {
      const apiKeySetting = new Setting(containerEl)
        .setName("API key")
        .setDesc(meta.apiKeyUrl
          ? `Enter your API key. Get one at: ${meta.apiKeyLabel}`
          : "Enter your API key."
        )
        .addText((text) =>
          text
            .setPlaceholder("sk-…")
            .setValue(this.plugin.settings.providerApiKey)
            .onChange(async (value) => {
              this.plugin.settings.providerApiKey = value.trim();
              await this.plugin.saveSettings();
            }),
        );

      apiKeySetting.controlEl.querySelector("input")?.setAttribute("type", "password");

      if (meta.apiKeyUrl) {
        apiKeySetting.descEl.createEl("br");
        apiKeySetting.descEl.createEl("a", {
          text: meta.apiKeyLabel ?? meta.apiKeyUrl,
          href: meta.apiKeyUrl,
          cls: "ai-os-api-key-link",
        });
      }
    }

    // Base URL (Ollama and custom providers)
    if (!meta.fixedBaseUrl) {
      new Setting(containerEl)
        .setName("Base URL")
        .setDesc("The base URL of the API endpoint.")
        .addText((text) =>
          text
            .setPlaceholder(meta.defaultBaseUrl ?? "https://…")
            .setValue(this.plugin.settings.providerBaseUrl)
            .onChange(async (value) => {
              this.plugin.settings.providerBaseUrl = value.trim();
              await this.plugin.saveSettings();
            }),
        );
    }

    // Synthesis model
    new Setting(containerEl)
      .setName("Synthesis model")
      .setDesc("Model used for planning and writing research reports. Leave blank to use the backend default.")
      .addText((text) =>
        text
          .setPlaceholder(meta.defaultSynthesisModel || "model name")
          .setValue(this.plugin.settings.synthesisModel)
          .onChange(async (value) => {
            this.plugin.settings.synthesisModel = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    // Judge model
    new Setting(containerEl)
      .setName("Judge model")
      .setDesc("Smaller/faster model used for the query-complexity check. Leave blank to use the synthesis model.")
      .addText((text) =>
        text
          .setPlaceholder(meta.defaultJudgeModel || meta.defaultSynthesisModel || "model name")
          .setValue(this.plugin.settings.judgeModel)
          .onChange(async (value) => {
            this.plugin.settings.judgeModel = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    // ── Related notes ────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "Related notes" });

    new Setting(containerEl)
      .setName("Enabled")
      .setDesc("Automatically show related notes in the side panel as you navigate.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.surfacingEnabled).onChange(async (value) => {
          this.plugin.settings.surfacingEnabled = value;
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Response delay (ms)")
      .setDesc("How long to wait after switching notes before searching for related content.")
      .addText((text) =>
        text
          .setValue(String(this.plugin.settings.surfaceDebounceMs))
          .onChange(async (value) => {
            const n = Number.parseInt(value, 10);
            if (Number.isFinite(n) && n >= 0) {
              this.plugin.settings.surfaceDebounceMs = n;
              await this.plugin.saveSettings();
            }
          }),
      );

    new Setting(containerEl)
      .setName("Results count")
      .setDesc("Maximum number of related passages to show per note.")
      .addText((text) =>
        text
          .setValue(String(this.plugin.settings.surfaceTopK))
          .onChange(async (value) => {
            const n = Number.parseInt(value, 10);
            if (Number.isFinite(n) && n > 0) {
              this.plugin.settings.surfaceTopK = n;
              await this.plugin.saveSettings();
            }
          }),
      );

    // ── Research ─────────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "Research" });

    new Setting(containerEl)
      .setName("Output folder")
      .setDesc("Where finished research reports are written as new notes.")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.researchOutputFolder)
          .setValue(this.plugin.settings.researchOutputFolder)
          .onChange(async (value) => {
            this.plugin.settings.researchOutputFolder =
              value.trim() || DEFAULT_SETTINGS.researchOutputFolder;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Search depth")
      .setDesc("How many passages the AI considers per question. Higher values improve coverage but take longer.")
      .addText((text) =>
        text
          .setValue(String(this.plugin.settings.researchK))
          .onChange(async (value) => {
            const n = Number.parseInt(value, 10);
            if (Number.isFinite(n) && n > 0) {
              this.plugin.settings.researchK = n;
              await this.plugin.saveSettings();
            }
          }),
      );

    new Setting(containerEl)
      .setName("Auto-correction passes")
      .setDesc("How many times to automatically fix citation issues before accepting the answer. Higher values improve accuracy but take longer.")
      .addText((text) =>
        text
          .setValue(String(this.plugin.settings.researchMaxRepairAttempts))
          .onChange(async (value) => {
            const n = Number.parseInt(value, 10);
            if (Number.isFinite(n) && n >= 0) {
              this.plugin.settings.researchMaxRepairAttempts = n;
              await this.plugin.saveSettings();
            }
          }),
      );

    new Setting(containerEl)
      .setName("Query expansion")
      .setDesc(
        "Automatic (recommended) lets the AI decide whether to break complex questions into focused sub-questions for more thorough answers. Always forces this. Never disables it for faster single-pass answers.",
      )
      .addDropdown((dd) =>
        dd
          .addOption("auto", "Automatic")
          .addOption("always", "Always")
          .addOption("never", "Never")
          .setValue(this.plugin.settings.researchDecompose)
          .onChange(async (value) => {
            this.plugin.settings.researchDecompose =
              value as "auto" | "always" | "never";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Show source details in reports")
      .setDesc(
        "Append a detailed source log to each report showing which passages were retrieved and cited. Useful for verifying the AI's reasoning.",
      )
      .addToggle((toggle) =>
        toggle
          .setValue(this.plugin.settings.researchShowDebug)
          .onChange(async (value) => {
            this.plugin.settings.researchShowDebug = value;
            await this.plugin.saveSettings();
          }),
      );
  }
}
