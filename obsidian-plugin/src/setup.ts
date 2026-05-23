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
    this.renderStep(
      contentEl,
      "1",
      "Install Ollama",
      (el) => {
        el.createEl("p", { text: "Download and install Ollama from:" });
        el.createEl("code", { text: "https://ollama.ai" });
        el.createEl("p", { text: "Then pull the required models:" });
        const pre = el.createEl("pre");
        pre.createEl("code", {
          text: [
            "ollama pull nomic-embed-text",
            "ollama pull qwen2.5:7b-instruct",
            "ollama pull qwen2.5:14b-instruct",
          ].join("\n"),
        });
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
          text: "Clone the repository and install with uv (recommended) or pip:",
        });
        const pre = el.createEl("pre");
        pre.createEl("code", {
          text: [
            "git clone https://github.com/hamish-hb/ai-os",
            "cd ai-os",
            "pip install uv   # skip if uv already installed",
            "uv sync",
          ].join("\n"),
        });
      },
    );

    this.renderStep(
      contentEl,
      "3",
      "Create your config",
      (el) => {
        el.createEl("p", { text: "Run the interactive setup wizard:" });
        const pre = el.createEl("pre");
        pre.createEl("code", { text: "uv run ai-os setup" });

        el.createEl("p", { text: "Your vault is at:" });
        const pathEl = el.createEl("pre");
        pathEl.createEl("code", { text: vaultPath, cls: "ai-os-setup-modal__vault-path" });
        el.createEl("p", {
          text: "The wizard will ask for this path — copy it from above.",
          cls: "ai-os-setup-modal__hint",
        });
      },
    );

    this.renderStep(
      contentEl,
      "4",
      "Ingest your vault",
      (el) => {
        const pre = el.createEl("pre");
        pre.createEl("code", { text: "uv run ai-os ingest" });
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
        const pre = el.createEl("pre");
        pre.createEl("code", { text: "uv run ai-os serve" });
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
