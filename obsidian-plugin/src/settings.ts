// Plugin settings. See docs/01_MVP_SCOPE.md, docs/04_PROJECT_STRUCTURE.md.
//
// The plugin owns no model config — all inference happens server-side (ADR-0005,
// ADR-0009). These knobs are HTTP + UX-only.
import { App, PluginSettingTab, Setting } from "obsidian";
import type AiOsPlugin from "./main";

export interface AiOsSettings {
  /** Orchestrator base URL. v0.1 is localhost-only. */
  backendUrl: string;
  /** Vault folder where deep-research reports are written. */
  researchOutputFolder: string;
  /** Surfacing side panel toggle. */
  surfacingEnabled: boolean;
  /** Debounce window for active-leaf-change → /surface calls. */
  surfaceDebounceMs: number;
  /** Top-K passed to /surface. */
  surfaceTopK: number;
  /** Client-side similarity threshold for the surfacing panel (0..1). Results
   *  with score < this are hidden in the side panel — the backend still returns
   *  the full top-K, the slider just controls what's drawn. */
  surfaceMinScore: number;
  /** Top-K passed to /research (retrieval breadth before synth). */
  researchK: number;
  /** Bounded repair attempts the citation engine may take. */
  researchMaxRepairAttempts: number;
  /** Atomizer override (v0.2.2, sign-off #7). "auto" lets the judge model
   *  decide; true/false skips the Atomizer LLM call. */
  researchDecompose: "auto" | "always" | "never";
  /** Append the v0.2.2 diagnostic shim (per-Executor retrieval log) to the
   *  generated report. Off by default — keeps reports clean. Sign-off Q1. */
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
    containerEl.createEl("h2", { text: "AI OS" });

    // ── Backend ──────────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "Backend" });

    new Setting(containerEl)
      .setName("Orchestrator URL")
      .setDesc("The local FastAPI orchestrator. v0.1 is localhost-only.")
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
      .setDesc("Hit /health and report what the orchestrator sees.")
      .addButton((btn) =>
        btn
          .setButtonText("Check")
          .onClick(async () => {
            await this.plugin.checkHealth();
          }),
      );

    // ── Surfacing ────────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "Proactive surfacing" });

    new Setting(containerEl)
      .setName("Enabled")
      .setDesc("Push related blocks into the side panel when the active note changes.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.surfacingEnabled).onChange(async (value) => {
          this.plugin.settings.surfacingEnabled = value;
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Debounce (ms)")
      .setDesc("Quiet window before sending the active note to /surface.")
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
      .setName("Top K")
      .setDesc("Maximum related blocks to surface per note.")
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

    // ── Deep research ────────────────────────────────────────────────────────
    containerEl.createEl("h3", { text: "Deep research" });

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
      .setName("Retrieval K")
      .setDesc("How many chunks the synthesiser sees per query.")
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
      .setName("Max repair attempts")
      .setDesc("Bounded retries when citation verification fails (ADR-0013).")
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
      .setName("Decomposition")
      .setDesc(
        "Atomizer override (ADR-0021). 'Auto' lets the judge model decide " +
          "whether to break the query into focused sub-queries. 'Always' " +
          "forces decomposition. 'Never' runs a single-pass query " +
          "(matches v0.2.1 behaviour, skips the Atomizer LLM call).",
      )
      .addDropdown((dd) =>
        dd
          .addOption("auto", "Auto (Atomizer decides)")
          .addOption("always", "Always decompose")
          .addOption("never", "Never decompose")
          .setValue(this.plugin.settings.researchDecompose)
          .onChange(async (value) => {
            this.plugin.settings.researchDecompose =
              value as "auto" | "always" | "never";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Append debug section to reports")
      .setDesc(
        "Append a collapsed debug section to each report showing the " +
          "Atomizer's rationale and the per-Executor retrieval log " +
          "(block ids, scores, attempts). Useful when investigating why " +
          "the model cited a particular block.",
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
