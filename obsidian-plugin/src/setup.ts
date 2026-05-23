// First-run setup guide. Shown when the backend is unreachable.
import { App, Modal, FileSystemAdapter } from "obsidian";

export function getVaultPath(app: App): string {
  const adapter = app.vault.adapter;
  if (adapter instanceof FileSystemAdapter) {
    return adapter.getBasePath();
  }
  return "(vault path unavailable)";
}

export class SetupModal extends Modal {
  constructor(app: App) {
    super(app);
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("ai-os-setup-modal");

    contentEl.createEl("h2", { text: "AI OS — Backend Setup" });
    contentEl.createEl("p", {
      text:
        "AI OS requires a local Python backend. All inference runs on your " +
        "machine — nothing in your vault is sent to the cloud.",
      cls: "ai-os-setup-modal__intro",
    });

    const vaultPath = getVaultPath(this.app);

    // ── Quick Start ──────────────────────────────────────────────────────────
    const qs = contentEl.createDiv({ cls: "ai-os-setup-modal__quickstart" });
    qs.createEl("h3", { text: "Quick Start" });
    qs.createEl("p", {
      text: "Already have Ollama installed? Three steps and you're done.",
      cls: "ai-os-setup-modal__hint",
    });

    this.renderQsBlock(
      qs,
      "A — Clone & install",
      [
        "git clone https://github.com/Slaymish/async-researcher",
        "cd async-researcher",
        "uv sync --all-packages",
      ].join("\n"),
    );

    this.renderQsBlock(
      qs,
      "B — Configure (vault path pre-filled)",
      `uv run ai-os setup --yes --vault ${JSON.stringify(vaultPath)}`,
    );

    this.renderQsBlock(
      qs,
      "C — Index & run",
      ["uv run ai-os ingest", "uv run ai-os serve"].join("\n"),
    );

    contentEl.createEl("hr", { cls: "ai-os-setup-modal__divider" });

    // ── Detailed steps ───────────────────────────────────────────────────────
    contentEl.createEl("h3", { text: "Step by step" });

    this.renderStep(
      contentEl,
      "1",
      "Install Ollama",
      (el) => {
        el.createEl("p", { text: "Download and install Ollama from:" });
        this.addCodeBlock(el, "https://ollama.ai");
        el.createEl("p", { text: "Then pull the required models:" });
        this.addCodeBlock(
          el,
          [
            "ollama pull nomic-embed-text",
            "ollama pull qwen2.5:7b-instruct",
            "ollama pull qwen2.5:14b-instruct",
          ].join("\n"),
        );
        el.createEl("p", {
          text: "The 14b model (~9 GB) is used for synthesis. You can substitute a smaller model and update config.toml accordingly.",
          cls: "ai-os-setup-modal__hint",
        });
      },
    );

    this.renderStep(
      contentEl,
      "2",
      "Install the backend",
      (el) => {
        el.createEl("p", {
          text: "Clone the repository and install with uv:",
        });
        this.addCodeBlock(
          el,
          [
            "git clone https://github.com/Slaymish/async-researcher",
            "cd async-researcher",
            "pip install uv   # skip if uv already installed",
            "uv sync --all-packages",
          ].join("\n"),
        );
      },
    );

    this.renderStep(
      contentEl,
      "3",
      "Create your config",
      (el) => {
        el.createEl("p", {
          text: "Run the setup wizard (your vault path is pre-filled below):",
        });
        this.addCodeBlock(
          el,
          `uv run ai-os setup --yes --vault ${JSON.stringify(vaultPath)}`,
        );
        el.createEl("p", {
          text: "Or run without --yes for an interactive wizard where you can customise model choices.",
          cls: "ai-os-setup-modal__hint",
        });
      },
    );

    this.renderStep(
      contentEl,
      "4",
      "Ingest your vault",
      (el) => {
        this.addCodeBlock(el, "uv run ai-os ingest");
        el.createEl("p", {
          text: "This indexes your notes. May take a few minutes on a large vault.",
          cls: "ai-os-setup-modal__hint",
        });
      },
    );

    this.renderStep(
      contentEl,
      "5",
      "Start the backend",
      (el) => {
        this.addCodeBlock(el, "uv run ai-os serve");
        el.createEl("p", {
          text: "On macOS, you can add this to Login Items so it starts automatically.",
          cls: "ai-os-setup-modal__hint",
        });
      },
    );

    const footer = contentEl.createDiv({ cls: "ai-os-setup-modal__footer" });
    footer.createEl("p", {
      text: "Once the backend is running, go to Settings → AI OS and click Check connection.",
    });

    const closeBtn = footer.createEl("button", {
      text: "Close",
      cls: "mod-cta",
    });
    closeBtn.addEventListener("click", () => this.close());
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private addCodeBlock(parent: HTMLElement, text: string): void {
    const wrapper = parent.createDiv({ cls: "ai-os-setup-modal__code-wrap" });
    const pre = wrapper.createEl("pre");
    pre.createEl("code", { text });

    const btn = wrapper.createEl("button", {
      cls: "ai-os-setup-modal__copy-btn",
      text: "Copy",
    });
    btn.addEventListener("click", async () => {
      await navigator.clipboard.writeText(text);
      btn.setText("Copied!");
      setTimeout(() => btn.setText("Copy"), 1500);
    });
  }

  private renderQsBlock(parent: HTMLElement, label: string, text: string): void {
    const block = parent.createDiv({ cls: "ai-os-setup-modal__qs-block" });
    block.createEl("p", { text: label, cls: "ai-os-setup-modal__qs-label" });
    this.addCodeBlock(block, text);
  }

  private renderStep(
    parent: HTMLElement,
    num: string,
    title: string,
    body: (el: HTMLElement) => void,
  ): void {
    const stepEl = parent.createDiv({ cls: "ai-os-setup-modal__step" });
    const headEl = stepEl.createDiv({ cls: "ai-os-setup-modal__step-head" });
    headEl.createSpan({ cls: "ai-os-setup-modal__step-num", text: num });
    headEl.createSpan({ cls: "ai-os-setup-modal__step-title", text: title });
    const bodyEl = stepEl.createDiv({ cls: "ai-os-setup-modal__step-body" });
    body(bodyEl);
  }
}
