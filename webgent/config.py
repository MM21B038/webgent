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

_DOCKER_CHROMIUM_ARGS = (
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
)


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env")


def _env_str(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    return str(raw).strip()


def _env_flag(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str) -> int | None:
    raw = _env_str(name)
    if raw is None:
        return None
    return int(raw)


def _env_float(name: str) -> float | None:
    raw = _env_str(name)
    if raw is None:
        return None
    return float(raw)


def _pick_str(env_name: str, toml_value: object, default: str) -> str:
    env = _env_str(env_name)
    if env is not None:
        return env
    if toml_value is None:
        return default
    return str(toml_value)


def _pick_int(env_name: str, toml_value: object, default: int) -> int:
    env = _env_int(env_name)
    if env is not None:
        return env
    if toml_value is None:
        return default
    return int(toml_value)


def _pick_float(env_name: str, toml_value: object, default: float) -> float:
    env = _env_float(env_name)
    if env is not None:
        return env
    if toml_value is None:
        return default
    return float(toml_value)


def _pick_bool(env_name: str, toml_value: object, default: bool) -> bool:
    env = _env_flag(env_name)
    if env is not None:
        return env
    if toml_value is None:
        return default
    return bool(toml_value)


def running_in_docker() -> bool:
    flag = _env_flag("WEBGENT_IN_DOCKER")
    if flag is not None:
        return flag
    return Path("/.dockerenv").is_file()


@dataclass(frozen=True)
class BrowserSettings:
    headless: bool = False
    display: str = ""
    chromium_args: tuple[str, ...] = ()


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
    server_info_resource: str = SERVER_INFO_RESOURCE_URI
    prompt: str = PROMPT_NAME

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

def settings_file_path() -> Path:
    override = _env_str("WEBGENT_SETTINGS_PATH")
    if override is not None:
        return Path(override)
    return SETTINGS_PATH


def _load_toml() -> dict:
    path = settings_file_path()
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _chromium_args() -> tuple[str, ...]:
    args: list[str] = []
    if running_in_docker():
        args.extend(_DOCKER_CHROMIUM_ARGS)
    extra = os.environ.get("WEBGENT_CHROMIUM_ARGS", "").strip()
    if extra:
        for part in extra.replace(",", " ").split():
            if part:
                args.append(part)
    seen: set[str] = set()
    unique: list[str] = []
    for arg in args:
        if arg not in seen:
            seen.add(arg)
            unique.append(arg)
    return tuple(unique)


def load_settings() -> Settings:
    _load_dotenv()
    data = _load_toml()
    browser = data.get("browser", {})
    proxy = data.get("proxy", {})
    server = data.get("server", {})
    mcp = data.get("mcp", {}).get("cursor", {})
    agent = data.get("agent", {})
    snapshot = data.get("snapshot", {})
    host = _pick_str("WEBGENT_SERVER_HOST", server.get("host"), "127.0.0.1")
    port = _pick_int("WEBGENT_SERVER_PORT", server.get("port"), 1234)
    headless = _pick_bool("WEBGENT_HEADLESS", browser.get("headless"), False)
    if running_in_docker() and _env_flag("WEBGENT_HEADLESS") is None:
        headless = True
    cursor_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    mcp_url_default = f"http://{cursor_host}:{port}/mcp"
    return Settings(
        browser=BrowserSettings(
            headless=headless,
            display=_pick_str("WEBGENT_DISPLAY", browser.get("display"), ""),
            chromium_args=_chromium_args(),
        ),
        proxy=ProxySettings(
            enabled=_pick_bool("WEBGENT_PROXY_ENABLED", proxy.get("enabled"), True),
            mode=_pick_str("WEBGENT_PROXY_MODE", proxy.get("mode"), "embedded"),
            host=_pick_str("WEBGENT_PROXY_HOST", proxy.get("host"), "127.0.0.1"),
            port=_pick_int("WEBGENT_PROXY_PORT", proxy.get("port"), 8888),
            external_server=_pick_str(
                "WEBGENT_PROXY_EXTERNAL_SERVER",
                proxy.get("external_server"),
                "",
            ),
            max_body_bytes=_pick_int(
                "WEBGENT_PROXY_MAX_BODY_BYTES",
                proxy.get("max_body_bytes"),
                1_048_576,
            ),
            bypass_loopback=_pick_bool(
                "WEBGENT_PROXY_BYPASS_LOOPBACK",
                proxy.get("bypass_loopback"),
                False,
            ),
        ),
        server=ServerSettings(
            transport=_pick_str(
                "WEBGENT_SERVER_TRANSPORT",
                server.get("transport"),
                "http",
            ),
            host=host,
            port=port,
        ),
        snapshot=SnapshotSettings(
            list_threshold=_pick_int(
                "WEBGENT_SNAPSHOT_LIST_THRESHOLD",
                snapshot.get("list_threshold"),
                30,
            ),
            list_head=_pick_int(
                "WEBGENT_SNAPSHOT_LIST_HEAD",
                snapshot.get("list_head"),
                10,
            ),
            list_tail=_pick_int(
                "WEBGENT_SNAPSHOT_LIST_TAIL",
                snapshot.get("list_tail"),
                10,
            ),
            iframe_retry_count=_pick_int(
                "WEBGENT_SNAPSHOT_IFRAME_RETRY_COUNT",
                snapshot.get("iframe_retry_count"),
                2,
            ),
            iframe_retry_delay_s=_pick_float(
                "WEBGENT_SNAPSHOT_IFRAME_RETRY_DELAY_S",
                snapshot.get("iframe_retry_delay_s"),
                0.5,
            ),
        ),
        mcp_cursor=McpCursorSettings(
            url=_pick_str("WEBGENT_MCP_URL", mcp.get("url"), mcp_url_default),
            server_info_resource=_pick_str(
                "WEBGENT_MCP_SERVER_INFO_RESOURCE",
                mcp.get("server_info_resource"),
                SERVER_INFO_RESOURCE_URI,
            ),
            prompt=_pick_str("WEBGENT_MCP_PROMPT", mcp.get("prompt"), PROMPT_NAME),
        ),
        agent=AgentSettings(
            llm_model=_pick_str(
                "WEBGENT_LLM_MODEL",
                agent.get("llm_model"),
                "DeepSeek",
            ),
            vlm_model=_pick_str(
                "WEBGENT_VLM_MODEL",
                agent.get("vlm_model"),
                "VisionChat",
            ),
            emb_model=_pick_str(
                "WEBGENT_EMB_MODEL",
                agent.get("emb_model"),
                "Qwen3-Embedding-8B",
            ),
        ),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def apply_browser_env() -> None:
    override = os.environ.get("WEBGENT_DISPLAY")
    if override is not None:
        display = override.strip()
        if display:
            os.environ["DISPLAY"] = display
        return
    if running_in_docker():
        return
    display = get_settings().browser.display.strip()
    if display:
        os.environ["DISPLAY"] = display
