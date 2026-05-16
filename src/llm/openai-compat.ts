import { requestUrl } from "obsidian";

interface OpenAICompatOpts {
  baseUrl: string;
  apiKey: string;
  model: string;
  system: string;
  user: string;
  temperature?: number;
  extraHeaders?: Record<string, string>;
}

export async function callOpenAICompat(opts: OpenAICompatOpts): Promise<string> {
  const resp = await requestUrl({
    url: `${opts.baseUrl.replace(/\/+$/, "")}/chat/completions`,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${opts.apiKey || "no-key"}`,
      ...opts.extraHeaders,
    },
    body: JSON.stringify({
      model: opts.model,
      temperature: opts.temperature ?? 0.3,
      messages: [
        { role: "system", content: opts.system },
        { role: "user", content: opts.user },
      ],
    }),
    throw: false,
  });

  if (resp.status >= 400) {
    throw new Error(`LLM HTTP ${resp.status}: ${resp.text.slice(0, 300)}`);
  }

  const json = resp.json as {
    choices?: { message?: { content?: string } }[];
    error?: { message?: string };
  };
  if (json.error) throw new Error(`LLM error: ${json.error.message ?? "unknown"}`);
  return json.choices?.[0]?.message?.content ?? "";
}
