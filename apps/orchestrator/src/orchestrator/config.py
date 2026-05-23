"""Config loading. Reads `config.toml` from repo root (or `$AI_OS_CONFIG`) at startup.

Single source of truth: the file. Environment variables are not interpolated except for
`${data_dir}` expansion within the `[storage]` section and tilde-expansion on paths.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VaultConfig:
    path: Path
    inbox_dirs: list[str]


@dataclass(frozen=True)
class StorageConfig:
    data_dir: Path
    duckdb_path: Path
    lightrag_dir: Path


@dataclass(frozen=True)
class InferenceSectionConfig:
    base_url: str
    api_key: str
    synthesis_model: str
    embedding_model: str
    judge_model: str
    embedding_dim: int  # set per-model; nomic-embed-text = 768
    timeout_s: float


@dataclass(frozen=True)
class WatcherConfig:
    debounce_ms: int
    ignore_globs: list[str]


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int


@dataclass(frozen=True)
class WebConfig:
    searxng_url: str | None  # e.g. "http://localhost:8888"; None = DDGS only
    max_fetch_urls: int  # cap on URLs fetched per sub-query
    fetch_timeout_s: float


@dataclass(frozen=True)
class AppConfig:
    vault: VaultConfig
    storage: StorageConfig
    inference: InferenceSectionConfig
    watcher: WatcherConfig
    server: ServerConfig
    web: WebConfig


def _expand(p: str | Path, data_dir: Path | None = None) -> Path:
    s = str(p)
    if data_dir is not None:
        s = s.replace("${data_dir}", str(data_dir))
    return Path(os.path.expanduser(s)).resolve()


# nomic-embed-text → 768; mxbai-embed-large → 1024. Override via [inference].embedding_dim
# if a user picks something else.
_DEFAULT_EMBEDDING_DIMS = {
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "bge-large": 1024,
}


def user_config_dir() -> Path:
    """Platform-appropriate user config directory for AI OS."""
    import sys

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ai_os"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "ai-os"
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    return Path(xdg) / "ai-os" if xdg else Path.home() / ".config" / "ai-os"


def _config_path() -> Path:
    env = os.environ.get("AI_OS_CONFIG")
    if env:
        return Path(env).resolve()
    # Walk upwards from cwd to find a config.toml.
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        candidate = parent / "config.toml"
        if candidate.is_file():
            return candidate
    # Fall back to platform-appropriate user config directory.
    user_cfg = user_config_dir() / "config.toml"
    if user_cfg.is_file():
        return user_cfg
    raise FileNotFoundError(
        "config.toml not found.\n"
        "Run `ai-os setup` to create one, or copy config.toml.example and set "
        "AI_OS_CONFIG to its path."
    )


def load_config(path: Path | None = None) -> AppConfig:
    cfg_path = path or _config_path()
    with cfg_path.open("rb") as f:
        raw = tomllib.load(f)

    storage_raw = raw["storage"]
    data_dir = _expand(storage_raw["data_dir"])
    storage = StorageConfig(
        data_dir=data_dir,
        duckdb_path=_expand(storage_raw["duckdb_path"], data_dir),
        lightrag_dir=_expand(storage_raw["lightrag_dir"], data_dir),
    )

    vault_raw = raw["vault"]
    vault = VaultConfig(
        path=_expand(vault_raw["path"]),
        inbox_dirs=list(vault_raw.get("inbox_dirs", [])),
    )

    inf_raw = raw["inference"]
    embedding_model = inf_raw["embedding_model"]
    embedding_dim = (
        inf_raw["embedding_dim"]
        if "embedding_dim" in inf_raw
        else _DEFAULT_EMBEDDING_DIMS.get(embedding_model)
    )
    if embedding_dim is None:
        raise ValueError(
            f"Unknown embedding_dim for model '{embedding_model}'. "
            "Set [inference].embedding_dim in config.toml."
        )
    inference = InferenceSectionConfig(
        base_url=inf_raw["base_url"],
        api_key=inf_raw.get("api_key", ""),
        synthesis_model=inf_raw["synthesis_model"],
        embedding_model=embedding_model,
        judge_model=inf_raw["judge_model"],
        embedding_dim=int(embedding_dim),
        timeout_s=float(inf_raw.get("timeout_s", 300.0)),
    )

    watcher_raw = raw.get("watcher", {})
    watcher = WatcherConfig(
        debounce_ms=int(watcher_raw.get("debounce_ms", 500)),
        ignore_globs=list(watcher_raw.get("ignore_globs", [])),
    )

    server_raw = raw.get("server", {})
    server = ServerConfig(
        host=server_raw.get("host", "127.0.0.1"),
        port=int(server_raw.get("port", 8765)),
    )

    web_raw = raw.get("web", {})
    web = WebConfig(
        searxng_url=web_raw.get("searxng_url") or None,
        max_fetch_urls=int(web_raw.get("max_fetch_urls", 5)),
        fetch_timeout_s=float(web_raw.get("fetch_timeout_s", 30.0)),
    )

    return AppConfig(
        vault=vault,
        storage=storage,
        inference=inference,
        watcher=watcher,
        server=server,
        web=web,
    )
