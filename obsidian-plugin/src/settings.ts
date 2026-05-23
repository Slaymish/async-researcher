import { App, PluginSettingTab, Setting } from "obsidian";
import type AiOsPlugin from "./main";
import { SetupModal, getVaultPath } from "./setup";

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
        text.setValue(getVaultPath(this.app)).setDisabled(true);
        text.inputEl.style.width = "100%";
        text.inputEl.style.fontFamily = "monospace";
        text.inputEl.style.fontSize = "0.85em";
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
