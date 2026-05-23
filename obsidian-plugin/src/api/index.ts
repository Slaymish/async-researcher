// HTTP client to the orchestrator backend.
//
// All requests go through Obsidian's `requestUrl` (bypasses CORS and works
// inside the desktop renderer). The plugin is the only client of this API
// per docs/04_PROJECT_STRUCTURE.md §"Inter-process protocols".
//
// Contract sources:
//   - GET  /health           apps/orchestrator/src/orchestrator/routes/health.py
//   - POST /research         apps/orchestrator/src/orchestrator/routes/research.py
//   - POST /surface          apps/orchestrator/src/orchestrator/routes/surface.py
import { requestUrl } from "obsidian";

export interface HealthResponse {
  status: string;
  vault: string | null;
  file_count: number;
  chunk_count: number;
}

export interface SurfaceChunk {
  relpath: string;
  block_id: string;
  text: string;
  score: number;
  kind?: string;
}

export interface SurfaceResponse {
  results: SurfaceChunk[];
}

export interface SurfaceRequest {
  relpath: string;
  content: string;
  k?: number;
}

export interface ResearchRequest {
  query: string;
  k?: number;
  max_repair_attempts?: number;
  max_sub_queries?: number;
  skip_alignment?: boolean;
  /** v0.2.2 sign-off #7: Atomizer override. "auto" (default) asks the judge
   *  model; true/false bypasses the Atomizer LLM call entirely. */
  decompose?: "auto" | boolean;
}

export interface ResearchFailure {
  kind: string;
  section: string;
  claim: string;
  block_id: string | null;
  detail: string;
}

/** v0.2.2 diagnostic shim — per-Executor retrieval log. */
export interface ResearchExecution {
  sub_query: string;
  rationale: string;
  attempts: number;
  pass_rate: number;
  failures: ResearchFailure[];
  chunks: { block_id: string; relpath: string; score: number }[];
}

export interface ResearchResponse {
  query: string;
  markdown: string;
  attempts: number;
  pass_rate: number;
  failures: ResearchFailure[];
  /** v0.2.2: present unless the user overrode `decompose` (then null). */
  atomizer: { decompose: boolean; rationale: string } | null;
  /** v0.2.2: one entry per Executor that ran. Always at least 1. */
  executions: ResearchExecution[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: string,
  ) {
    super(message);
  }
}

export class OrchestratorClient {
  constructor(private readonly getBaseUrl: () => string) {}

  async health(): Promise<HealthResponse> {
    return this.get<HealthResponse>("/health");
  }

  async surface(req: SurfaceRequest): Promise<SurfaceResponse> {
    return this.post<SurfaceResponse>("/surface", req);
  }

  async research(req: ResearchRequest): Promise<ResearchResponse> {
    return this.post<ResearchResponse>("/research", req);
  }

  private async get<T>(path: string): Promise<T> {
    const resp = await requestUrl({
      url: this.url(path),
      method: "GET",
      throw: false,
    });
    return this.unwrap<T>(resp.status, resp.text, resp.json);
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const resp = await requestUrl({
      url: this.url(path),
      method: "POST",
      contentType: "application/json",
      body: JSON.stringify(body),
      throw: false,
    });
    return this.unwrap<T>(resp.status, resp.text, resp.json);
  }

  private url(path: string): string {
    const base = this.getBaseUrl().replace(/\/+$/, "");
    return `${base}${path}`;
  }

  private unwrap<T>(status: number, text: string, json: unknown): T {
    if (status >= 400) {
      throw new ApiError(
        `Orchestrator HTTP ${status}: ${text.slice(0, 300)}`,
        status,
        text,
      );
    }
    return json as T;
  }
}
