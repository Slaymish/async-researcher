import { callOllama } from "./ollama";
import { callOpenAICompat } from "./openai-compat";

export type LlmProviderKind = "ollama" | "openai" | "anthropic" | "openrouter" | "openai_compat";

export interface LlmProviderMeta {
  label: string;
  baseUrl: string;
  keyUrl: string;
  keyPlaceholder: string;
  modelPlaceholder: string;
}

export const LLM_PROVIDERS: Record<LlmProviderKind, LlmProviderMeta> = {
  ollama: {
    label: "Ollama (local)",
    baseUrl: "http://localhost:11434",
    keyUrl: "",
    keyPlaceholder: "",
    modelPlaceholder: "llama3.2",
  },
  openai: {
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    keyUrl: "https://platform.openai.com/api-keys",
    keyPlaceholder: "sk-...",
    modelPlaceholder: "gpt-4o",
  },
  anthropic: {
    label: "Anthropic",
    baseUrl: "https://api.anthropic.com/v1",
    keyUrl: "https://console.anthropic.com/settings/keys",
    keyPlaceholder: "sk-ant-...",
    modelPlaceholder: "claude-sonnet-4-5",
  },
  openrouter: {
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    keyUrl: "https://openrouter.ai/keys",
    keyPlaceholder: "sk-or-...",
    modelPlaceholder: "anthropic/claude-sonnet-4-5",
  },
  openai_compat: {
    label: "OpenAI-compatible (custom)",
    baseUrl: "",
    keyUrl: "",
    keyPlaceholder: "API key",
    modelPlaceholder: "model-name",
  },
};

export interface LlmSettings {
  llmProvider: LlmProviderKind;
  llmBaseUrl: string;
  llmApiKey: string;
  llmModel: string;
}

export interface LlmCallOpts {
  expectJson?: boolean;
  temperature?: number;
}

export type LlmFn = (
  system: string,
  user: string,
  opts?: LlmCallOpts,
) => Promise<string>;

let inflight: Promise<unknown> = Promise.resolve();

export function getLlm(settings: LlmSettings): LlmFn {
  return async (system, user, opts = {}) => {
    const previous = inflight;
    let release!: () => void;
    inflight = new Promise<void>((resolve) => {
      release = resolve;
    });

    try {
      await previous;
      return await dispatch(settings, system, user, opts);
    } finally {
      release();
    }
  };
}

function resolvedBaseUrl(settings: LlmSettings): string {
  const saved = settings.llmBaseUrl.trim();
  if (saved) return saved;
  return LLM_PROVIDERS[settings.llmProvider]?.baseUrl ?? "";
}

async function dispatch(
  settings: LlmSettings,
  system: string,
  user: string,
  opts: LlmCallOpts,
) {
  if (!settings.llmModel.trim()) {
    throw new Error("No LLM model configured.");
  }

  const baseUrl = resolvedBaseUrl(settings);

  switch (settings.llmProvider) {
    case "ollama":
      return callOllama({
        baseUrl,
        model: settings.llmModel,
        system,
        user,
        format: opts.expectJson ? "json" : undefined,
        temperature: opts.temperature,
      });
    case "anthropic":
      return callOpenAICompat({
        baseUrl,
        apiKey: settings.llmApiKey,
        model: settings.llmModel,
        system,
        user,
        temperature: opts.temperature,
        extraHeaders: {
          "anthropic-version": "2023-06-01",
          "x-api-key": settings.llmApiKey,
        },
      });
    case "openai":
    case "openrouter":
    case "openai_compat":
      return callOpenAICompat({
        baseUrl,
        apiKey: settings.llmApiKey,
        model: settings.llmModel,
        system,
        user,
        temperature: opts.temperature,
      });
  }
}
