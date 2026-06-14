from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "profile"
MEDIA_DIR = PROJECT_ROOT / "media"
REGISTRY_DIR = PROJECT_ROOT / "registry"
MITMPROXY_DIR = PROJECT_ROOT / "mitmproxy"
SETTINGS_PATH = PROJECT_ROOT / "settings.toml"
README_PATH = PROJECT_ROOT / "README.md"
PROMPT_PATH = PROJECT_ROOT / "prompt.md"
SERVER_INFO_RESOURCE_URI = "webgent://server-info"
PROMPT_NAME = "agent_system_prompt"


@dataclass(frozen=True)
class BrowserSettings:
    headless: bool = False
    display: str = ""


@dataclass(frozen=True)
class ProxySettings:
    enabled: bool = True
    mode: str = "embedded"  # embedded | external
    host: str = "127.0.0.1"
    port: int = 8888
    external_server: str = ""
    max_body_bytes: int = 1_048_576
    bypass_loopback: bool = False


@dataclass(frozen=True)
class ServerSettings:
    transport: str = "http"
    host: str = "127.0.0.1"
    port: int = 1234


@dataclass(frozen=True)
class SnapshotSettings:
    list_threshold: int = 30
    list_head: int = 10
    list_tail: int = 10
    iframe_retry_count: int = 2
    iframe_retry_delay_s: float = 0.5


@dataclass(frozen=True)
class McpCursorSettings:
    url: str = "http://127.0.0.1:1234/mcp"

@dataclass(frozen=True)
class AgentSettings:
    llm_model: str = "DeepSeek"
    vlm_model: str = "VisionChat"
    emb_model: str = "Qwen3-Embedding-8B"


@dataclass(frozen=True)
class Settings:
    browser: BrowserSettings
    proxy: ProxySettings
    server: ServerSettings
    snapshot: SnapshotSettings
    mcp_cursor: McpCursorSettings
    agent: AgentSettings

def _load_toml() -> dict:
    if not SETTINGS_PATH.is_file():
        return {}
    with SETTINGS_PATH.open("rb") as handle:
        return tomllib.load(handle)


def load_settings() -> Settings:
    data = _load_toml()
    browser = data.get("browser", {})
    proxy = data.get("proxy", {})
    server = data.get("server", {})
    mcp = data.get("mcp", {}).get("cursor", {})
    agent = data.get("agent", {})
    snapshot = data.get("snapshot", {})
    host = str(server.get("host", "127.0.0.1"))
    port = int(os.environ.get("WEBGENT_SERVER_PORT", server.get("port", 1234)))
    return Settings(
        browser=BrowserSettings(
            headless=bool(browser.get("headless", False)),
            display=str(browser.get("display", "")),
        ),
        proxy=ProxySettings(
            enabled=bool(proxy.get("enabled", True)),
            mode=str(proxy.get("mode", "embedded")),
            host=str(proxy.get("host", "127.0.0.1")),
            port=int(proxy.get("port", 8888)),
            external_server=str(proxy.get("external_server", "")),
            max_body_bytes=int(proxy.get("max_body_bytes", 1_048_576)),
            bypass_loopback=bool(proxy.get("bypass_loopback", False)),
        ),
        server=ServerSettings(
            transport=str(server.get("transport", "http")),
            host=host,
            port=port,
        ),
        snapshot=SnapshotSettings(
            list_threshold=int(snapshot.get("list_threshold", 30)),
            list_head=int(snapshot.get("list_head", 10)),
            list_tail=int(snapshot.get("list_tail", 10)),
            iframe_retry_count=int(snapshot.get("iframe_retry_count", 2)),
            iframe_retry_delay_s=float(snapshot.get("iframe_retry_delay_s", 0.5)),
        ),
        mcp_cursor=McpCursorSettings(
            url=str(mcp.get("url", f"http://{host}:{port}/mcp")),
        ),
        agent=AgentSettings(
            llm_model=str(agent.get("llm_model", "DeepSeek")),
            vlm_model=str(agent.get("vlm_model", "VisionChat")),
            emb_model=str(agent.get("emb_model", "Qwen3-Embedding-8B")),
        ),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def apply_browser_env() -> None:
    display = get_settings().browser.display.strip()
    if display:
        os.environ["DISPLAY"] = display
