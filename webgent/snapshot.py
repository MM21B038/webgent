from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal
from playwright.async_api import Locator, Page

_REF_RE = re.compile(r"^e\d+$")
_REF_IN_LINE_RE = re.compile(r"\[ref=(e\d+)\]")
_URL_LINE_RE = re.compile(r"^(\s*-\s*/url:\s*)(.+)$")
DEFAULT_MAX_URL_LEN = 80
DEFAULT_GET_NODE_DEPTH = 3
SnapshotFormat = Literal["interactive", "tree"]
_TREE_REF_LINE_RE = re.compile(
    r"^(\s*)- (.+?) \[ref=(e\d+)\](.*?)(?::\s*)?$"
)
_COMPACT_REF_LINE_RE = re.compile(r"^(\s*)- \[(e\d+)\]\s+")
_ROLE_NAME_RE = re.compile(r'^(\S+)\s+"([^"]*)"(.*)$')
_CHILD_OPTION_RE = re.compile(r'^(\s*)- option "([^"]*)"(.*)$')
_CHILD_OPTION_QUOTED_RE = re.compile(r"""^(\s*)- 'option "([^"]*)"'(.*)$""")
_CHILD_OPTION_REF_RE = re.compile(
    r'^(\s*)- option "([^"]*)" \[ref=(e\d+)\](.*?)(?::\s*)?$'
)
_OPTION_CONTAINER_ROLES = frozenset({"combobox", "listbox"})
_FORM_CONTROL_STATE_RE = re.compile(
    r"\[(checked|unchecked|selected|pressed|expanded|collapsed|disabled|required|invalid|readonly)\]"
)
_STRUCTURAL_NAME_KEYWORDS = (
    "navigation",
    "main content",
    "skip to",
    "shortcuts menu",
    "banner",
    "footer",
    "header",
    "complementary",
    "region",
)

# WAI-ARIA widget roles and common actionable implicit roles from aria snapshots.
INTERACTIVE_ROLES = frozenset(
    {
        "button",
        "link",
        "textbox",
        "searchbox",
        "combobox",
        "listbox",
        "checkbox",
        "radio",
        "switch",
        "slider",
        "scrollbar",
        "spinbutton",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "tab",
        "option",
        "treeitem",
        "gridcell",
        "row",
        "cell",
        "columnheader",
        "rowheader",
        "summary",
        "listitem",
        "img",
        "image",
        "file",
    }
)


def parse_role_name(body: str) -> tuple[str, str | None]:
    name_match = _ROLE_NAME_RE.match(body)
    if name_match:
        return name_match.group(1).lower(), name_match.group(2)
    parts = body.split()
    if parts:
        return parts[0].lower(), None
    return body.lower(), None


def normalize_interactive_role(role: str) -> str:
    return "img" if role == "image" else role


def _is_structural_name(name: str | None) -> bool:
    if not name:
        return False
    lower = name.lower()
    return any(keyword in lower for keyword in _STRUCTURAL_NAME_KEYWORDS)


def is_interactive_role(role: str, suffix: str, *, name: str | None = None) -> bool:
    normalized = normalize_interactive_role(role)
    if normalized in INTERACTIVE_ROLES:
        return True
    if "cursor=pointer" in suffix:
        return True
    if normalized in {"generic", "group", "label", "listitem"} and (
        _FORM_CONTROL_STATE_RE.search(suffix) is not None
    ):
        return True
    if normalized in {"generic", "group", "label"} and name and not _is_structural_name(name):
        return True
    return False


def format_interactable_line(
    ref: str,
    role: str,
    name: str | None = None,
    *,
    states: str = "",
    option_suffix: str = "",
) -> str:
    normalized_role = normalize_interactive_role(role)
    if name:
        body = f'{normalized_role} "{name}"'
    else:
        body = normalized_role
    line = f"- [{ref}] {body}"
    if states:
        line += f" {states.strip()}"
    if option_suffix:
        line += option_suffix
    return line


def compact_interactive_line(
    line: str,
    *,
    option_suffix: str = "",
) -> str | None:
    stripped = line.rstrip()
    match = _TREE_REF_LINE_RE.match(stripped)
    if match is None:
        return None
    body = match.group(2).strip()
    ref = match.group(3)
    suffix = match.group(4).strip()
    if suffix.endswith(":"):
        suffix = suffix[:-1].strip()

    role, name = parse_role_name(body)
    if role == "image":
        body = f'img "{name}"' if name else "img"
    if not is_interactive_role(role, suffix, name=name):
        return None

    compact = f"- [{ref}] {body}"
    if suffix:
        compact += f" {suffix}"
    if option_suffix:
        compact += option_suffix
    return compact


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_child_option(line: str) -> tuple[str | None, str, str] | None:
    ref_match = _CHILD_OPTION_REF_RE.match(line.rstrip())
    if ref_match:
        extra = ref_match.group(4).strip()
        if extra.endswith(":"):
            extra = extra[:-1].strip()
        return ref_match.group(3), ref_match.group(2), extra
    for pattern in (_CHILD_OPTION_RE, _CHILD_OPTION_QUOTED_RE):
        opt_match = pattern.match(line.rstrip())
        if opt_match:
            extra = opt_match.group(3).strip()
            if extra.endswith(":"):
                extra = extra[:-1].strip()
            return None, opt_match.group(2), extra
    return None


def _collect_child_options(
    lines: list[str],
    start: int,
    parent_indent: int,
) -> list[tuple[str | None, str, str]]:
    options: list[tuple[str | None, str, str]] = []
    child_indent = parent_indent + 2
    for line in lines[start:]:
        if not line.strip():
            continue
        indent = _line_indent(line)
        if indent <= parent_indent:
            break
        if indent != child_indent:
            continue
        parsed = _parse_child_option(line)
        if parsed is not None:
            options.append(parsed)
    return options


def _format_options_suffix(options: list[tuple[str | None, str, str]]) -> str:
    if not options:
        return ""
    parts: list[str] = []
    for ref, name, extra in options:
        piece = f'"{name}"'
        if ref:
            piece = f"[{ref}] {piece}"
        if extra:
            piece = f"{piece} {extra}"
        parts.append(piece)
    return f" options={' | '.join(parts)}"


def _split_options_suffix(line: str) -> tuple[str, str | None]:
    marker = " options="
    index = line.find(marker)
    if index == -1:
        return line, None
    return line[:index], line[index:]


def _format_dom_options(options: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for option in options:
        label = str(option.get("label", "")).strip()
        if not label:
            continue
        piece = f'"{label}"'
        if option.get("selected"):
            piece += " [selected]"
        parts.append(piece)
    if not parts:
        return ""
    return f" options={' | '.join(parts)}"


_FETCH_COMBOBOX_OPTIONS_JS = """(el) => {
    const toOption = (node) => {
        const label = (
            node.getAttribute('aria-label')
            || node.label
            || node.textContent
            || node.value
            || ''
        ).trim();
        if (!label) return null;
        return {
            label,
            selected: Boolean(
                node.selected
                || node.getAttribute('aria-selected') === 'true'
                || node.hasAttribute('selected')
            ),
        };
    };

    if (el.tagName === 'SELECT') {
        return [...el.options].map(toOption).filter(Boolean);
    }

    let listbox = null;
    const controls = el.getAttribute('aria-controls');
    if (controls) {
        listbox = document.getElementById(controls);
    }
    if (!listbox) {
        const owns = el.getAttribute('aria-owns');
        if (owns) {
            for (const id of owns.split(/\\s+/)) {
                listbox = document.getElementById(id);
                if (listbox) break;
            }
        }
    }
    if (!listbox) {
        const sibling = el.nextElementSibling;
        if (sibling && sibling.getAttribute('role') === 'listbox') {
            listbox = sibling;
        }
    }
    if (!listbox) {
        listbox = el.querySelector('[role=listbox]')
            || el.parentElement?.querySelector('[role=listbox]');
    }
    if (!listbox) {
        return null;
    }
    return [...listbox.querySelectorAll('[role=option], option')]
        .map(toOption)
        .filter(Boolean);
}"""


_RESOLVE_INTERACTABLE_ROLE_JS = """(el) => {
    const tag = el.tagName;
    const type = (el.type || '').toLowerCase();
    if (tag === 'INPUT') {
        if (type === 'file') return 'file';
        if (type === 'checkbox') {
            if (el.getAttribute('role') === 'switch') return 'switch';
            return 'checkbox';
        }
        if (type === 'radio') return 'radio';
        if (type === 'range') return 'slider';
        if (type === 'number') return 'spinbutton';
        if (type === 'search') return 'searchbox';
        if (type === 'button' || type === 'submit' || type === 'reset') return 'button';
        if (type === 'hidden') return null;
        return 'textbox';
    }
    if (tag === 'SELECT') return 'combobox';
    if (tag === 'TEXTAREA') return 'textbox';
    if (tag === 'SUMMARY') return 'summary';
    if (tag === 'IMG') return 'img';
    if (tag === 'BUTTON') {
        const role = (el.getAttribute('role') || '').toLowerCase();
        if (role === 'tab') return 'tab';
        return 'button';
    }
    if (tag === 'A' && el.href) return 'link';
    const role = (el.getAttribute('role') || '').toLowerCase();
    return role || null;
}"""


def normalize_ref(ref: str) -> str:
    value = ref.strip()
    if value.startswith("[ref=") and value.endswith("]"):
        value = value[5:-1]
    if value.startswith("ref="):
        value = value[4:]
    if not _REF_RE.match(value):
        raise ValueError(
            f"Invalid ref {ref!r}. Use a ref from the latest snapshot, e.g. e12."
        )
    return value


def ref_locator(page: Page, ref: str) -> Locator:
    normalized = normalize_ref(ref)
    return page.locator(f"aria-ref={normalized}")


async def read_locator_value(locator: Locator) -> str:
    try:
        value = await locator.input_value()
        if value:
            return value
    except Exception:
        pass
    return str(await locator.evaluate("el => el.value ?? ''"))


def _click_intercepted(exc: BaseException) -> bool:
    return "intercepts pointer" in str(exc).lower()


async def click_ref(page: Page, ref: str) -> None:
    locator = ref_locator(page, ref)
    try:
        await locator.click()
    except Exception as exc:
        if not _click_intercepted(exc):
            raise
        clicked_overlay = await locator.evaluate(
            """(el) => {
                const rect = el.getBoundingClientRect();
                const x = rect.left + rect.width / 2;
                const y = rect.top + rect.height / 2;
                const target = document.elementFromPoint(x, y);
                if (!target || target === el) return false;
                target.click();
                return true;
            }"""
        )
        if not clicked_overlay:
            await locator.click(force=True)


def extract_ref_from_line(line: str) -> str | None:
    match = _REF_IN_LINE_RE.search(line)
    if match:
        return match.group(1)
    compact = _COMPACT_REF_LINE_RE.match(line)
    if compact:
        return compact.group(2)
    return None


def format_structural_line(role: str, name: str | None = None) -> str:
    normalized = normalize_interactive_role(role)
    if name:
        return f'- {normalized} "{name}":'
    return f"- {normalized}:"


@dataclass
class _TreeNode:
    indent: int
    role: str
    name: str | None
    ref: str | None
    suffix: str
    children: list[_TreeNode] = field(default_factory=list)
    raw_line: str = ""


def _parse_tree_lines(lines: list[str]) -> list[_TreeNode]:
    roots: list[_TreeNode] = []
    stack: list[tuple[int, _TreeNode]] = []

    for line in lines:
        if not line.strip():
            continue
        indent = _line_indent(line)
        stripped = line.rstrip()

        while stack and stack[-1][0] >= indent:
            stack.pop()

        parent = stack[-1][1] if stack else None

        ref_match = _TREE_REF_LINE_RE.match(stripped)
        if ref_match is not None:
            body = ref_match.group(2).strip()
            ref = ref_match.group(3)
            suffix = ref_match.group(4).strip()
            if suffix.endswith(":"):
                suffix = suffix[:-1].strip()
            role, name = parse_role_name(body)
            node = _TreeNode(
                indent=indent,
                role=role,
                name=name,
                ref=ref,
                suffix=suffix,
                raw_line=stripped,
            )
            if parent is not None:
                parent.children.append(node)
            else:
                roots.append(node)
            stack.append((indent, node))
            continue

        option_parsed = _parse_child_option(stripped)
        if option_parsed is not None and parent is not None:
            opt_ref, opt_name, opt_extra = option_parsed
            parent.children.append(
                _TreeNode(
                    indent=indent,
                    role="option",
                    name=opt_name,
                    ref=opt_ref,
                    suffix=opt_extra,
                    raw_line=stripped,
                )
            )

    return roots


_OPTION_CHILD_ROLES = frozenset(
    {"option", "menuitem", "menuitemcheckbox", "menuitemradio"}
)


def _collect_option_nodes(node: _TreeNode) -> list[tuple[str | None, str, str]]:
    options: list[tuple[str | None, str, str]] = []
    for child in node.children:
        if child.role in _OPTION_CHILD_ROLES:
            options.append((child.ref, child.name or "", child.suffix))
    return options


def _should_collapse_structural(node: _TreeNode, child_nodes: list[_TreeNode]) -> bool:
    if node.role not in {"generic", "group"}:
        return False
    if is_interactive_role(node.role, node.suffix, name=node.name):
        return False
    return any(
        not is_interactive_role(child.role, child.suffix, name=child.name)
        for child in child_nodes
    )


def _trim_interactable_node(node: _TreeNode, indent: int) -> list[str]:
    prefix = " " * indent
    option_suffix = ""
    child_nodes = node.children
    if node.role in _OPTION_CONTAINER_ROLES:
        options = _collect_option_nodes(node)
        if options:
            option_suffix = _format_options_suffix(options)
        child_nodes = [c for c in node.children if c.role not in _OPTION_CHILD_ROLES]

    interactive = is_interactive_role(node.role, node.suffix, name=node.name)
    if not interactive and _should_collapse_structural(node, child_nodes):
        promoted: list[str] = []
        for child in child_nodes:
            promoted.extend(_trim_interactable_node(child, indent))
        return promoted

    trimmed_children: list[str] = []
    for child in child_nodes:
        trimmed_children.extend(_trim_interactable_node(child, indent + 2))

    if interactive:
        assert node.ref is not None
        line = format_interactable_line(
            node.ref,
            node.role,
            node.name,
            states=node.suffix,
            option_suffix=option_suffix,
        )
        if trimmed_children:
            return [f"{prefix}{line}:"] + trimmed_children
        return [f"{prefix}{line}"]

    if trimmed_children:
        header = format_structural_line(node.role, node.name)
        return [f"{prefix}{header}"] + trimmed_children
    return []


def to_interactive_snapshot(tree_yaml: str) -> str:
    roots = _parse_tree_lines(tree_yaml.splitlines())
    output: list[str] = []
    for root in roots:
        output.extend(_trim_interactable_node(root, 0))
    return "\n".join(output)


def apply_snapshot_format(tree_yaml: str, snapshot_format: SnapshotFormat) -> str:
    if snapshot_format == "tree":
        return tree_yaml
    return to_interactive_snapshot(tree_yaml)


def parse_node_headline(line: str) -> dict[str, Any]:
    compact = _COMPACT_REF_LINE_RE.match(line)
    ref = compact.group(2) if compact else None
    stripped = line.strip()
    if ref is not None:
        stripped = stripped[len(f"- [{ref}]") :].strip()
        if " options=" in stripped:
            stripped = stripped.split(" options=", 1)[0].strip()
    else:
        match = _REF_IN_LINE_RE.search(line)
        ref = match.group(1) if match else None
        if ref is not None:
            stripped = _REF_IN_LINE_RE.sub("", stripped).strip()

    if stripped.endswith(":"):
        stripped = stripped[:-1].strip()
    role = stripped
    name = None
    name_match = _ROLE_NAME_RE.match(stripped)
    if name_match:
        role = name_match.group(1)
        name = name_match.group(2)
    states: list[str] = []
    for token_match in re.finditer(r"\[([^\]=]+(?:=[^\]]+)?)\]", line):
        token = token_match.group(1)
        if token.startswith("ref=") or re.fullmatch(r"e\d+", token):
            continue
        states.append(token)
    return {
        "ref": ref,
        "role": role,
        "name": name,
        "states": states,
    }


async def _normalize_interactable_line_from_dom(page: Page, line: str) -> str:
    compact = _COMPACT_REF_LINE_RE.match(line)
    if compact is None:
        return line
    indent, ref = compact.groups()
    base_line, options_part = _split_options_suffix(line.strip())
    rest = base_line.strip()[len(f"- [{ref}]") :].strip()
    if " options=" in rest:
        rest = rest.split(" options=", 1)[0].strip()
    parsed_role, name = parse_role_name(rest)
    states = rest
    if name:
        name_match = _ROLE_NAME_RE.match(rest)
        states = name_match.group(3) if name_match else ""
    else:
        states = rest[len(parsed_role) :].strip() if rest.startswith(parsed_role) else ""
    try:
        resolved_role = await ref_locator(page, ref).evaluate(_RESOLVE_INTERACTABLE_ROLE_JS)
    except Exception:
        return line
    if not resolved_role or resolved_role == parsed_role:
        return line
    normalized = normalize_interactive_role(resolved_role)
    rebuilt = format_interactable_line(
        ref,
        normalized,
        name,
        states=states.strip(),
        option_suffix=options_part or "",
    )
    return f"{indent}{rebuilt}"


async def enrich_interactables(page: Page, interactables: str) -> str:
    enriched: list[str] = []
    for line in interactables.splitlines():
        if not line.strip():
            enriched.append(line)
            continue
        compact = _COMPACT_REF_LINE_RE.match(line)
        if compact is None:
            enriched.append(line)
            continue
        indent, ref = compact.groups()
        base_line, _existing = _split_options_suffix(line.strip())
        rest = base_line.strip()[len(f"- [{ref}]") :].strip()
        role, _name = parse_role_name(rest)
        if role not in _OPTION_CONTAINER_ROLES:
            enriched.append(line)
            continue
        try:
            options = await ref_locator(page, ref).evaluate(_FETCH_COMBOBOX_OPTIONS_JS)
        except Exception:
            options = None
        if options:
            suffix = _format_dom_options(options)
            if suffix:
                base, _ = _split_options_suffix(line.rstrip())
                enriched.append(base + suffix)
            else:
                enriched.append(line)
        else:
            enriched.append(line)
    normalized = "\n".join(enriched)
    final: list[str] = []
    for line in normalized.splitlines():
        if not line.strip():
            final.append(line)
            continue
        final.append(await _normalize_interactable_line_from_dom(page, line))
    return "\n".join(final)


def truncate_url(url: str, max_len: int = DEFAULT_MAX_URL_LEN) -> str:
    value = url.strip()
    if len(value) <= max_len:
        return value
    if max_len <= 1:
        return "…"
    return f"{value[: max_len - 1]}…"


def compress_snapshot(
    raw: str,
    *,
    include_urls: bool = False,
    max_url_len: int = DEFAULT_MAX_URL_LEN,
) -> str:
    lines: list[str] = []
    for line in raw.splitlines():
        match = _URL_LINE_RE.match(line)
        if match is None:
            lines.append(line)
            continue
        if not include_urls:
            continue
        prefix, url_value = match.groups()
        lines.append(f"{prefix}{truncate_url(url_value, max_url_len)}")
    return "\n".join(lines)


async def capture_page_snapshot(
    page: Page,
    *,
    ref: str | None = None,
    depth: int | None = None,
    boxes: bool = False,
    include_urls: bool = False,
    max_url_len: int = DEFAULT_MAX_URL_LEN,
    snapshot_format: SnapshotFormat = "interactive",
) -> str:
    if ref is not None:
        raw = await ref_locator(page, ref).aria_snapshot(
            mode="ai",
            depth=depth,
            boxes=boxes,
        )
        # Subtree snapshots only stamp refs inside the scope; refresh the full page
        # so other elements keep stable aria-ref markers for follow-up actions.
        await page.aria_snapshot(mode="ai")
    else:
        raw = await page.aria_snapshot(mode="ai", depth=depth, boxes=boxes)
    tree = compress_snapshot(
        raw,
        include_urls=include_urls,
        max_url_len=max_url_len,
    )
    formatted = apply_snapshot_format(tree, snapshot_format)
    if snapshot_format == "interactive":
        formatted = await enrich_interactables(page, formatted)
    return formatted


async def capture_tree_snapshot(
    page: Page,
    *,
    ref: str | None = None,
    depth: int | None = None,
    boxes: bool = False,
    include_urls: bool = False,
    max_url_len: int = DEFAULT_MAX_URL_LEN,
) -> str:
    return await capture_page_snapshot(
        page,
        ref=ref,
        depth=depth,
        boxes=boxes,
        include_urls=include_urls,
        max_url_len=max_url_len,
        snapshot_format="tree",
    )


async def snapshot_result(
    page: Page,
    page_id: str,
    *,
    scope_ref: str | None = None,
    depth: int | None = None,
    boxes: bool = False,
    include_urls: bool = False,
    max_url_len: int = DEFAULT_MAX_URL_LEN,
    **extra: Any,
) -> dict[str, Any]:
    normalized_scope_ref = normalize_ref(scope_ref) if scope_ref else None
    return {
        "page_id": page_id,
        "url": page.url,
        "title": await page.title(),
        "scope_ref": normalized_scope_ref,
        "snapshot": await capture_page_snapshot(
            page,
            ref=normalized_scope_ref,
            depth=depth,
            boxes=boxes,
            include_urls=include_urls,
            max_url_len=max_url_len,
            snapshot_format="tree",
        ),
        **extra,
    }


async def interactables_result(
    page: Page,
    page_id: str,
    *,
    scope_ref: str | None = None,
    depth: int | None = None,
    boxes: bool = False,
    include_urls: bool = False,
    max_url_len: int = DEFAULT_MAX_URL_LEN,
) -> dict[str, Any]:
    normalized_scope_ref = normalize_ref(scope_ref) if scope_ref else None
    return {
        "page_id": page_id,
        "url": page.url,
        "title": await page.title(),
        "scope_ref": normalized_scope_ref,
        "interactables": await capture_page_snapshot(
            page,
            ref=normalized_scope_ref,
            depth=depth,
            boxes=boxes,
            include_urls=include_urls,
            max_url_len=max_url_len,
            snapshot_format="interactive",
        ),
    }


async def get_node_result(
    page: Page,
    page_id: str,
    ref: str,
    *,
    depth: int = DEFAULT_GET_NODE_DEPTH,
    include_urls: bool = False,
    max_url_len: int = DEFAULT_MAX_URL_LEN,
) -> dict[str, Any]:
    normalized = normalize_ref(ref)
    locator = ref_locator(page, normalized)
    if await locator.count() == 0:
        raise ValueError(f"Element {ref!r} was not found on the page")

    subtree = await capture_tree_snapshot(
        page,
        ref=normalized,
        depth=depth,
        include_urls=include_urls,
        max_url_len=max_url_len,
    )
    headline = next((line for line in subtree.splitlines() if line.strip()), "")
    parsed = parse_node_headline(headline)

    value: str | None = None
    try:
        value = await locator.input_value()
    except Exception:
        value = None

    checked: bool | None = None
    try:
        if await locator.evaluate(
            "el => el.matches('input[type=checkbox], input[type=radio]')"
        ):
            checked = await locator.is_checked()
    except Exception:
        checked = None

    return {
        "page_id": page_id,
        "ref": normalized,
        "role": parsed["role"],
        "name": parsed["name"],
        "states": parsed["states"],
        "value": value,
        "checked": checked,
        "subtree": subtree,
        "format": "tree",
    }


async def read_page_signals(page: Page) -> dict[str, Any]:
    return {
        "url": page.url,
        "title": await page.title(),
        "dialog_count": await page.get_by_role("dialog").count()
        + await page.get_by_role("alertdialog").count(),
    }
