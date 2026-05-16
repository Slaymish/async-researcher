import { requestUrl } from "obsidian";

interface OllamaOpts {
  baseUrl: string;
  model: string;
  system: string;
  user: string;
  format?: "json";
  temperature?: number;
}

export async function callOllama(opts: OllamaOpts): Promise<string> {
  const body: Record<string, unknown> = {
    model: opts.model,
    stream: false,
    messages: [
      { role: "system", content: opts.system },
      { role: "user", content: opts.user },
    ],
    options: {
      temperature: opts.temperature ?? 0.3,
    },
  };

  if (opts.format) body.format = opts.format;

  const resp = await requestUrl({
    url: `${normalizeOllamaBaseUrl(opts.baseUrl)}/api/chat`,
    method: "POST",
    contentType: "application/json",
    body: JSON.stringify(body),
    throw: false,
  });

  if (resp.status >= 400) {
    throw new Error(`Ollama HTTP ${resp.status}: ${resp.text.slice(0, 300)}`);
  }

  const json = resp.json as { message?: { content?: string }; error?: string };
  if (json.error) throw new Error(`Ollama error: ${json.error}`);
  return json.message?.content ?? "";
}

function normalizeOllamaBaseUrl(baseUrl: string) {
  return baseUrl.replace(/\/+$/, "").replace(/\/v1$/, "");
}
