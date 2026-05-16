#!/usr/bin/env python3
"""Deep-research sidecar — LLM-powered research runner.

Reads a run.json file, performs multi-step research using the configured LLM
provider, and writes report.md. Uses only Python 3 stdlib (urllib) — no pip
dependencies required.

LLM provider and model come from run.json; the API key is read from the
RESEARCHER_LLM_API_KEY environment variable so it is never written to disk.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Utilities ────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_status(run_path: Path, record: dict[str, Any]) -> None:
    write_json(
        run_path.parent / "status.json",
        {
            "id": record["id"],
            "status": record["status"],
            "progress": record["progress"],
            "reportPath": record["reportPath"],
            "updatedAt": record["updatedAt"],
        },
    )


def update_progress(
    run_path: Path, record: dict[str, Any], step: str, message: str, percent: int
) -> None:
    record["status"] = step
    record["progress"] = {"step": step, "message": message, "percent": percent}
    record["updatedAt"] = now_iso()
    write_json(run_path, record)
    write_status(run_path, record)


# ── LLM callers ──────────────────────────────────────────────────────────────

def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data, headers)
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())  # type: ignore[return-value]


def call_ollama(base_url: str, model: str, system: str, user: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    url += "/api/chat"
    result = _post_json(
        url,
        {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        {"Content-Type": "application/json"},
    )
    content = result.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"Empty response from Ollama: {result}")
    return content


def call_openai_compat(base_url: str, api_key: str, model: str, system: str, user: str) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    result = _post_json(
        url,
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key or 'no-key'}",
        },
    )
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"Empty response from LLM: {result}")
    return content


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_json_array(text: str) -> list[str]:
    attempts = [text.strip()]
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        attempts.append(m.group(1).strip())
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        attempts.append(m.group(0))

    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, list):
                return [str(s).strip() for s in parsed if str(s).strip()][:5]
        except Exception:
            pass
    return []


# ── Research engines ──────────────────────────────────────────────────────────

def run_llm_research(vault: Path, run_path: Path, record: dict[str, Any]) -> int:
    request = record.get("request", {})
    provider = request.get("llmProvider", "ollama")
    base_url = str(request.get("llmBaseUrl") or "http://localhost:11434/v1")
    model = str(request.get("llmModel") or "").strip()
    api_key = os.environ.get("RESEARCHER_LLM_API_KEY", "")
    context = str(request.get("context") or "").strip()

    if not model:
        update_progress(run_path, record, "failed", "No LLM model configured in plugin settings.", 0)
        return 1

    def llm(system: str, user: str) -> str:
        if provider == "ollama":
            return call_ollama(base_url, model, system, user)
        return call_openai_compat(base_url, api_key, model, system, user)

    try:
        # ── Step 1: Plan ─────────────────────────────────────────────────────
        update_progress(run_path, record, "planning", "Analyzing topic and planning research.", 10)

        plan_raw = llm(
            "You are a research planner. Return only a JSON array of strings.",
            (
                f"Research idea and context:\n\n{context}\n\n"
                "List 3 to 5 focused research questions that would produce a thorough report. "
                "Return a JSON array of question strings only. No commentary."
            ),
        )
        questions = parse_json_array(plan_raw)
        if not questions:
            questions = [f"What is known about: {context[:120]}?"]

        update_progress(run_path, record, "planning", f"Identified {len(questions)} research questions.", 20)

        # ── Step 2: Research each question ───────────────────────────────────
        findings: list[dict[str, str]] = []
        for i, question in enumerate(questions):
            pct = 25 + int((i / len(questions)) * 45)
            short_q = question[:70] + ("…" if len(question) > 70 else "")
            update_progress(run_path, record, "searching", f"Investigating: {short_q}", pct)

            answer = llm(
                "You are a knowledgeable research assistant. Provide thorough, well-sourced answers in markdown.",
                (
                    f"Context from the research idea:\n{context[:3000]}\n\n"
                    f"Research question:\n{question}\n\n"
                    "Provide a detailed, well-structured answer using markdown."
                ),
            )
            findings.append({"question": question, "answer": answer})

        # ── Step 3: Synthesize ────────────────────────────────────────────────
        update_progress(run_path, record, "synthesizing", "Synthesizing findings into a report.", 75)

        findings_block = "\n\n".join(
            f"### {f['question']}\n\n{f['answer']}" for f in findings
        )
        report_md = llm(
            "You are a research writer. Write clear, well-structured markdown research reports.",
            (
                f"Write a comprehensive research report on this topic:\n\n{context[:2000]}\n\n"
                f"Based on these research findings:\n\n{findings_block}\n\n"
                "Structure the report with: a brief executive summary, main findings organised by theme, "
                "and a conclusions section. Use markdown headings and bullet points where appropriate."
            ),
        )

        # ── Step 4: Write report ──────────────────────────────────────────────
        update_progress(run_path, record, "synthesizing", "Writing report file.", 90)
        report_path = vault / record["reportPath"]
        report_path.parent.mkdir(parents=True, exist_ok=True)
        title = record.get("noteTitle", "Research")
        report_path.write_text(
            f"# Research report: {title}\n\n{report_md.strip()}\n",
            encoding="utf-8",
        )

        update_progress(run_path, record, "completed", "Research complete.", 100)
        return 0

    except urllib.error.URLError as exc:
        msg = f"Could not reach LLM at {base_url}: {exc.reason}"
        update_progress(run_path, record, "failed", msg, record.get("progress", {}).get("percent", 0))
        return 1
    except Exception as exc:
        update_progress(run_path, record, "failed", str(exc), record.get("progress", {}).get("percent", 0))
        return 1


def run_stub(vault: Path, run_path: Path, record: dict[str, Any]) -> int:
    steps = [
        ("planning", "Planning search strategy.", 15),
        ("searching", "Stub search complete.", 40),
        ("fetching", "Stub source collection complete.", 65),
        ("synthesizing", "Writing stub report.", 85),
    ]
    try:
        import time
        for step, message, percent in steps:
            time.sleep(0.6)
            update_progress(run_path, record, step, message, percent)

        report_path = vault / record["reportPath"]
        report_path.parent.mkdir(parents=True, exist_ok=True)
        context = record["request"].get("context", "").strip() or "No context supplied."
        report_path.write_text(
            "\n".join([
                f"# Deep research: {record['noteTitle']}",
                "",
                "> Stub report — configure an LLM model to run real research.",
                "",
                "## Research brief",
                "",
                context,
                "",
            ]),
            encoding="utf-8",
        )
        update_progress(run_path, record, "completed", "Stub report complete.", 100)
        return 0
    except Exception as exc:
        update_progress(run_path, record, "failed", str(exc), record.get("progress", {}).get("percent", 0))
        return 1


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True, help="Absolute path to the Obsidian vault.")
    parser.add_argument("--run", required=True, help="Absolute path to run.json.")
    parser.add_argument(
        "--engine",
        choices=["auto", "stub", "llm"],
        default=os.environ.get("RESEARCHER_SIDECAR_ENGINE", "auto"),
        help="Research backend. auto and llm both run LLM research; stub runs the deterministic stub.",
    )
    args = parser.parse_args()

    vault = Path(args.vault)
    run_path = Path(args.run)
    record = read_json(run_path)

    if args.engine == "stub":
        return run_stub(vault, run_path, record)
    return run_llm_research(vault, run_path, record)


if __name__ == "__main__":
    raise SystemExit(main())
