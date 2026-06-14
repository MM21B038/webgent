from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from playwright.async_api import BrowserContext, Locator, Page

from webgent.config import get_settings

# Playwright aria snapshots use eN on the main frame and fNeM for cross-frame refs.
_ARIA_REF = r"(?:f\d+)?e\d+"
_REF_RE = re.compile(rf"^{_ARIA_REF}$")
_REF_IN_LINE_RE = re.compile(rf"\[ref=({_ARIA_REF})\]")
_URL_LINE_RE = re.compile(r"^(\s*-\s*/url:\s*)(.+)$")
DEFAULT_MAX_URL_LEN = 80
DEFAULT_GET_NODE_DEPTH = 3
DEFAULT_CLICK_TIMEOUT_MS = 10_000
SnapshotFormat = Literal["interactive", "tree"]
_TREE_REF_LINE_RE = re.compile(
    rf"^(\s*)- (.+?) \[ref=({_ARIA_REF})\](.*?)(?::\s*)?$"
)
_COMPACT_REF_LINE_RE = re.compile(rf"^(\s*)- \[({_ARIA_REF})\]\s+")
_ROLE_NAME_RE = re.compile(r'^(\S+)\s+"([^"]*)"(.*)$')
_CHILD_OPTION_RE = re.compile(r'^(\s*)- option "([^"]*)"(.*)$')
_CHILD_OPTION_QUOTED_RE = re.compile(r"""^(\s*)- 'option "([^"]*)"'(.*)$""")
_CHILD_OPTION_REF_RE = re.compile(
    rf'^(\s*)- option "([^"]*)" \[ref=({_ARIA_REF})\](.*?)(?::\s*)?$'
)
_IFRAME_UNAVAILABLE_SUFFIX = " (content unavailable)"
_REPETITIVE_SIBLING_ROLES = frozenset(
    {"row", "listitem", "generic", "gridcell", "cell", "table", "group"}
)
_VALUE_ENRICH_ROLES = frozenset(
    {"textbox", "searchbox", "textarea", "spinbutton", "slider"}
)
_CHECKED_ENRICH_ROLES = frozenset({"checkbox", "radio", "switch"})
_SELECTED_ENRICH_ROLES = frozenset({"combobox", "listbox"})
_ENRICH_SUFFIX_RE = re.compile(r'\b(value|checked|selected)=')


class ActionError(ValueError):
    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


def get_snapshot_settings() -> Any:
    return get_settings().snapshot


_IFRAME_REF_LINE_RE = re.compile(rf"^(\s*)- iframe\b.*\[ref=({_ARIA_REF})\]")

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
        if (
            type === 'button'
            || type === 'submit'
            || type === 'reset'
            || type === 'image'
        ) {
            return 'button';
        }
        if (type === 'hidden') return null;
        if (
            type === 'text'
            || type === 'password'
            || type === 'email'
            || type === 'tel'
            || type === 'url'
            || type === 'date'
            || type === 'time'
            || type === 'datetime-local'
            || type === 'month'
            || type === 'week'
            || type === 'color'
        ) {
            return 'textbox';
        }
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


async def _resolve_interactable_role(page: Page, ref: str) -> str | None:
    try:
        resolved = await ref_locator(page, ref).evaluate(_RESOLVE_INTERACTABLE_ROLE_JS)
    except Exception:
        return None
    if not resolved:
        return None
    return normalize_interactive_role(resolved)


def _rebuild_tree_ref_line(
    indent: str,
    role: str,
    name: str | None,
    ref: str,
    suffix: str,
    *,
    trailing_colon: bool = False,
) -> str:
    if name:
        body = f'{role} "{name}"'
    else:
        body = role
    line = f"{indent}- {body} [ref={ref}]"
    if suffix:
        line += suffix
    if trailing_colon:
        line += ":"
    return line


def normalize_ref(ref: str) -> str:
    value = ref.strip()
    if value.startswith("[ref=") and value.endswith("]"):
        value = value[5:-1]
    if value.startswith("ref="):
        value = value[4:]
    if not _REF_RE.match(value):
        raise ValueError(
            f"Invalid ref {ref!r}. Use a ref from the latest snapshot, "
            "e.g. e12 or f3e4."
        )
    return value


def ref_locator(page: Page, ref: str) -> Locator:
    normalized = normalize_ref(ref)
    return page.locator(f"aria-ref={normalized}")


_REF_NOT_FOUND_MSG = (
    "Call snapshot again to get fresh refs after navigation or DOM changes."
)


async def resolve_ref_locator(page: Page, ref: str) -> Locator:
    normalized = normalize_ref(ref)
    locator = ref_locator(page, normalized)
    if await locator.count() > 0:
        return locator
    await page.aria_snapshot(mode="ai")
    locator = ref_locator(page, normalized)
    if await locator.count() == 0:
        raise ActionError(
            f"Ref {normalized!r} not found on the page. {_REF_NOT_FOUND_MSG}",
            hint="Run snapshot to refresh refs after navigation or DOM changes.",
        )
    return locator


async def read_locator_value(locator: Locator) -> str:
    try:
        value = await locator.input_value()
        if value:
            return value
    except Exception:
        pass
    try:
        content = await locator.text_content()
        if content:
            return content
    except Exception:
        pass
    return str(await locator.evaluate("el => el.value ?? el.textContent ?? ''"))


_SYNC_INPUT_VALUE_JS = """(el, val) => {
    if (el.isContentEditable) {
        el.textContent = val;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return;
    }
    const proto = el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : el instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : null;
    if (!proto) return;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(el, val);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
}"""

_DETECT_FILL_STATE_JS = """(el) => ({
    readonly: Boolean(el.readOnly || el.getAttribute("readonly") !== null),
    disabled: Boolean(el.disabled),
    inputType: (el.type || "").toLowerCase(),
    jqueryDatepicker: el.classList.contains("hasDatepicker")
        && !!(window.jQuery?.fn?.datepicker),
    flatpickr: !!(el._flatpickr),
    nativeDate: el.tagName === "INPUT"
        && (el.type === "date" || el.type === "datetime-local"),
})"""

_SET_DATEPICKER_VALUE_JS = """(el, val) => {
    const text = String(val ?? "").trim();
    if (!text) return "";

    const parseDateValue = (input) => {
        let match = input.match(/^(\\d{4})-(\\d{2})-(\\d{2})$/);
        if (match) {
            return new Date(+match[1], +match[2] - 1, +match[3]);
        }
        match = input.match(/^(\\d{1,2})[-\\/](\\d{1,2})[-\\/](\\d{2,4})$/);
        if (match) {
            let year = +match[3];
            if (year < 100) {
                year += year > 50 ? 1900 : 2000;
            }
            return new Date(year, +match[2] - 1, +match[1]);
        }
        const parsed = new Date(input);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    };

    const formatIsoDate = (date) => {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    };

    const date = parseDateValue(text);
    if (!date) return "";

    if (el.classList.contains("hasDatepicker") && window.jQuery?.fn?.datepicker) {
        window.jQuery(el).datepicker("setDate", date);
        return el.value || "";
    }

    if (el._flatpickr) {
        el._flatpickr.setDate(date, true);
        return el.value || "";
    }

    if (el.type === "date" || el.type === "datetime-local") {
        const setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype,
            "value"
        )?.set;
        const iso = formatIsoDate(date);
        setter?.call(el, iso);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return el.value || "";
    }

    return "";
}"""


async def fill_ref(locator: Locator, value: str) -> str:
    state = await locator.evaluate(_DETECT_FILL_STATE_JS)
    if state.get("disabled"):
        raise ActionError(
            "Fill failed: element is disabled.",
            hint="Click the required tab, mode, or login trigger first, then snapshot again.",
        )

    is_datepicker = (
        state.get("jqueryDatepicker")
        or state.get("flatpickr")
        or state.get("nativeDate")
    )
    if state.get("readonly") and is_datepicker:
        actual = await locator.evaluate(_SET_DATEPICKER_VALUE_JS, value)
        if not actual:
            raise ValueError(
                f"Fill failed: could not set date {value!r}. "
                "Use dd-mm-yyyy or yyyy-mm-dd."
            )
        return actual
    if state.get("readonly"):
        raise ActionError(
            "Fill failed: element is readonly. "
            "If this is a date field, use fill with dd-mm-yyyy (e.g. 15-06-1990).",
            hint="Click the required tab, mode, or login trigger first, then snapshot again.",
        )

    await locator.fill(value)
    actual = await read_locator_value(locator)
    if actual != value:
        await locator.evaluate(_SYNC_INPUT_VALUE_JS, value)
        actual = await read_locator_value(locator)
    if actual != value:
        raise ValueError(
            f"Fill failed: expected {value!r}, got {actual!r}. "
            "The element may be readonly, disabled, or not an editable input."
        )
    return actual


def _click_intercepted(exc: BaseException) -> bool:
    return "intercepts pointer" in str(exc).lower()


async def click_ref(page: Page, ref: str) -> None:
    # Ref is validated in BrowserSession._run_action before this runs.
    locator = ref_locator(page, ref)
    click_kwargs = {
        "no_wait_after": True,
        "timeout": DEFAULT_CLICK_TIMEOUT_MS,
    }
    try:
        await locator.click(**click_kwargs)
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
            try:
                await locator.click(force=True, **click_kwargs)
            except Exception as force_exc:
                if _click_intercepted(force_exc):
                    raise ActionError(
                        str(force_exc),
                        hint=(
                            "Possible overlay, modal, or iframe is blocking the click. "
                            "Run snapshot, dismiss the blocker, then retry."
                        ),
                    ) from force_exc
                raise


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
            continue

        if parent is not None:
            parent.children.append(
                _TreeNode(
                    indent=indent,
                    role="raw",
                    name=None,
                    ref=None,
                    suffix="",
                    raw_line=stripped,
                )
            )

    return roots


_OPTION_CHILD_ROLES = frozenset(
    {"option", "menuitem", "menuitemcheckbox", "menuitemradio"}
)


def _is_selected_item(item: Any) -> bool:
    if isinstance(item, _TreeNode):
        suffix = item.suffix
        return "selected" in suffix or "checked" in suffix
    if isinstance(item, str):
        return "[selected]" in item or "[checked]" in item
    return False


def _truncate_indexed_sequence(
    items: list[Any],
    *,
    threshold: int,
    head: int,
    tail: int,
    ellipsis_label: str,
) -> list[Any]:
    if len(items) <= threshold:
        return items
    keep_indices: set[int] = set(range(min(head, len(items))))
    keep_indices.update(range(max(len(items) - tail, 0), len(items)))
    for index, item in enumerate(items):
        if _is_selected_item(item):
            keep_indices.add(index)
    ordered = sorted(keep_indices)
    result: list[Any] = []
    previous = -1
    for index in ordered:
        if previous >= 0 and index > previous + 1:
            result.append(("ellipsis", index - previous - 1, ellipsis_label))
        result.append(items[index])
        previous = index
    return result


def _truncate_inline_options_line(
    line: str,
    *,
    threshold: int,
    head: int,
    tail: int,
) -> str:
    base, suffix = _split_options_suffix(line)
    if suffix is None:
        return line
    content = suffix[len(" options=") :]
    parts = [part.strip() for part in content.split(" | ") if part.strip()]
    if len(parts) <= threshold:
        return line
    truncated = _truncate_indexed_sequence(
        parts,
        threshold=threshold,
        head=head,
        tail=tail,
        ellipsis_label="options",
    )
    rebuilt: list[str] = []
    for item in truncated:
        if isinstance(item, tuple) and item[0] == "ellipsis":
            rebuilt.append(f"... {item[1]} {item[2]} omitted ...")
        else:
            rebuilt.append(str(item))
    return f"{base} options={' | '.join(rebuilt)}"


def _ellipsis_tree_node(indent: int, count: int, label: str) -> _TreeNode:
    text = f"... {count} {label} omitted ..."
    return _TreeNode(
        indent=indent,
        role="ellipsis",
        name=None,
        ref=None,
        suffix="",
        raw_line=f'{" " * indent}- {text}',
    )


def _render_tree_node(node: _TreeNode) -> list[str]:
    if node.role == "ellipsis":
        return [node.raw_line]
    if node.role == "raw":
        return [node.raw_line]
    lines: list[str] = []
    if node.raw_line:
        header = node.raw_line
        if node.children and not header.rstrip().endswith(":"):
            header = header.rstrip() + ":"
        lines.append(header)
    elif node.ref is not None:
        body = f'{node.role} "{node.name}"' if node.name else node.role
        header = f'{" " * node.indent}- {body} [ref={node.ref}]'
        if node.suffix:
            header += f" {node.suffix}"
        if node.children:
            header += ":"
        lines.append(header)
    else:
        lines.append(f'{" " * node.indent}{format_structural_line(node.role, node.name)}')
    for child in node.children:
        lines.extend(_render_tree_node(child))
    return lines


def _render_tree_nodes(nodes: list[_TreeNode]) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.extend(_render_tree_node(node))
    return lines


def _truncate_tree_node(
    node: _TreeNode,
    threshold: int,
    head: int,
    tail: int,
) -> _TreeNode:
    option_children = [
        child for child in node.children if child.role in _OPTION_CHILD_ROLES
    ]
    other_children = [
        child for child in node.children if child.role not in _OPTION_CHILD_ROLES
    ]
    if node.role in _OPTION_CONTAINER_ROLES and len(option_children) > threshold:
        truncated_options = _truncate_indexed_sequence(
            option_children,
            threshold=threshold,
            head=head,
            tail=tail,
            ellipsis_label="options",
        )
        node.children = []
        for item in truncated_options:
            if isinstance(item, tuple) and item[0] == "ellipsis":
                node.children.append(
                    _ellipsis_tree_node(node.indent + 2, item[1], item[2])
                )
            else:
                node.children.append(_truncate_tree_node(item, threshold, head, tail))
        node.children.extend(
            _truncate_tree_node(child, threshold, head, tail)
            for child in other_children
        )
        return node

    node.children = _truncate_child_groups(
        node.children, node.indent, threshold, head, tail
    )
    return node


def _truncate_child_groups(
    children: list[_TreeNode],
    parent_indent: int,
    threshold: int,
    head: int,
    tail: int,
) -> list[_TreeNode]:
    result: list[_TreeNode] = []
    index = 0
    while index < len(children):
        role = children[index].role
        end = index + 1
        while (
            end < len(children)
            and children[end].role == role
            and role in _REPETITIVE_SIBLING_ROLES
        ):
            end += 1
        group = children[index:end]
        if len(group) > threshold:
            truncated = _truncate_indexed_sequence(
                group,
                threshold=threshold,
                head=head,
                tail=tail,
                ellipsis_label=f"{role}s",
            )
            for item in truncated:
                if isinstance(item, tuple) and item[0] == "ellipsis":
                    result.append(
                        _ellipsis_tree_node(parent_indent + 2, item[1], item[2])
                    )
                else:
                    result.append(_truncate_tree_node(item, threshold, head, tail))
        else:
            for child in group:
                result.append(_truncate_tree_node(child, threshold, head, tail))
        index = end
    return result


def truncate_repetitive_lists(
    tree_yaml: str,
    *,
    threshold: int = 30,
    head: int = 10,
    tail: int = 10,
) -> str:
    inline_truncated = "\n".join(
        _truncate_inline_options_line(
            line,
            threshold=threshold,
            head=head,
            tail=tail,
        )
        for line in tree_yaml.splitlines()
    )
    roots = _parse_tree_lines(inline_truncated.splitlines())
    truncated_roots = [
        _truncate_tree_node(node, threshold, head, tail) for node in roots
    ]
    return "\n".join(_render_tree_nodes(truncated_roots))


async def enrich_snapshot_state_from_dom(page: Page, tree_yaml: str) -> str:
    enriched: list[str] = []
    for line in tree_yaml.splitlines():
        if not line.strip() or _ENRICH_SUFFIX_RE.search(line):
            enriched.append(line)
            continue
        ref = extract_ref_from_line(line)
        if ref is None:
            enriched.append(line)
            continue
        parsed = parse_node_headline(line)
        role = normalize_interactive_role(parsed["role"])
        suffix_parts: list[str] = []
        locator = ref_locator(page, ref)
        try:
            if role in _VALUE_ENRICH_ROLES:
                value = await read_locator_value(locator)
                if value:
                    escaped = value.replace('"', '\\"')
                    suffix_parts.append(f'value="{escaped}"')
            elif role in _CHECKED_ENRICH_ROLES:
                checked = await locator.is_checked()
                suffix_parts.append(f"checked={'true' if checked else 'false'}")
            elif role in _SELECTED_ENRICH_ROLES:
                selected = await locator.input_value()
                if selected:
                    escaped = selected.replace('"', '\\"')
                    suffix_parts.append(f'selected="{escaped}"')
        except Exception:
            enriched.append(line)
            continue
        if not suffix_parts:
            enriched.append(line)
            continue
        trimmed = line.rstrip()
        trailing_colon = trimmed.endswith(":")
        if trailing_colon:
            trimmed = trimmed[:-1].rstrip()
        enriched.append(
            f"{trimmed} {' '.join(suffix_parts)}{':' if trailing_colon else ''}"
        )
    return "\n".join(enriched)


async def apply_snapshot_postprocessing(
    page: Page,
    tree_yaml: str,
    *,
    snapshot_format: SnapshotFormat,
) -> str:
    settings = get_snapshot_settings()
    processed = truncate_repetitive_lists(
        tree_yaml,
        threshold=settings.list_threshold,
        head=settings.list_head,
        tail=settings.list_tail,
    )
    if snapshot_format == "interactive":
        return await enrich_interactables(page, processed)
    processed = await enrich_snapshot_state_from_dom(page, processed)
    return await normalize_tree_roles_from_dom(page, processed)


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


def _extract_state_tokens(line: str) -> list[str]:
    states: list[str] = []
    for token_match in re.finditer(r"\[([^\]=]+(?:=[^\]]+)?)\]", line):
        token = token_match.group(1)
        if token.startswith("ref=") or _REF_RE.fullmatch(token):
            continue
        states.append(token)
    return states


def parse_node_headline(line: str) -> dict[str, Any]:
    stripped = line.rstrip()
    tree_match = _TREE_REF_LINE_RE.match(stripped)
    if tree_match is not None:
        body = tree_match.group(2).strip()
        ref = tree_match.group(3)
        suffix = tree_match.group(4).strip()
        if suffix.endswith(":"):
            suffix = suffix[:-1].strip()
        role, name = parse_role_name(body)
        states = _extract_state_tokens(suffix or stripped)
        return {
            "ref": ref,
            "role": role,
            "name": name,
            "states": states,
        }

    compact = _COMPACT_REF_LINE_RE.match(line)
    ref = compact.group(2) if compact else None
    rest = line.strip()
    if ref is not None:
        rest = rest[len(f"- [{ref}]") :].strip()
        if " options=" in rest:
            rest = rest.split(" options=", 1)[0].strip()
    else:
        match = _REF_IN_LINE_RE.search(line)
        ref = match.group(1) if match else None
        if ref is not None:
            rest = _REF_IN_LINE_RE.sub("", rest).strip()
            if rest.startswith("- "):
                rest = rest[2:].strip()

    if rest.endswith(":"):
        rest = rest[:-1].strip()
    role, name = parse_role_name(rest)
    return {
        "ref": ref,
        "role": role,
        "name": name,
        "states": _extract_state_tokens(line),
    }


async def resolve_ref_role(
    page: Page,
    ref: str,
    *,
    fallback_role: str | None = None,
) -> str:
    resolved = await _resolve_interactable_role(page, ref)
    if resolved:
        return resolved
    if fallback_role:
        return normalize_interactive_role(fallback_role)
    return "generic"


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
    resolved_role = await _resolve_interactable_role(page, ref)
    if not resolved_role or resolved_role == normalize_interactive_role(parsed_role):
        return line
    rebuilt = format_interactable_line(
        ref,
        resolved_role,
        name,
        states=states.strip(),
        option_suffix=options_part or "",
    )
    return f"{indent}{rebuilt}"


async def _normalize_tree_line_from_dom(page: Page, line: str) -> str:
    stripped = line.rstrip()
    match = _TREE_REF_LINE_RE.match(stripped)
    if match is None:
        return line
    indent, body, ref, suffix = match.groups()
    parsed_role, name = parse_role_name(body.strip())
    resolved_role = await _resolve_interactable_role(page, ref)
    if not resolved_role or resolved_role == normalize_interactive_role(parsed_role):
        return line
    trailing_colon = stripped.endswith(":")
    return _rebuild_tree_ref_line(
        indent,
        resolved_role,
        name,
        ref,
        suffix,
        trailing_colon=trailing_colon,
    )


async def normalize_tree_roles_from_dom(page: Page, tree_yaml: str) -> str:
    normalized: list[str] = []
    for line in tree_yaml.splitlines():
        if not line.strip():
            normalized.append(line)
            continue
        normalized.append(await _normalize_tree_line_from_dom(page, line))
    return "\n".join(normalized)


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


_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})


def is_html_content_type(content_type: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type in _HTML_CONTENT_TYPES


async def capture_html_snapshot(
    context: BrowserContext,
    html: str,
    *,
    snapshot_format: SnapshotFormat = "tree",
    include_urls: bool = False,
    max_url_len: int = DEFAULT_MAX_URL_LEN,
) -> str:
    page = await context.new_page()
    try:
        await page.set_content(html, wait_until="domcontentloaded")
        return await capture_page_snapshot(
            page,
            include_urls=include_urls,
            max_url_len=max_url_len,
            snapshot_format=snapshot_format,
        )
    finally:
        await page.close()


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


def _tree_node_has_children(lines: list[str], index: int) -> bool:
    if index >= len(lines):
        return False
    parent_indent = _line_indent(lines[index])
    for line in lines[index + 1 :]:
        if not line.strip():
            continue
        if _line_indent(line) <= parent_indent:
            break
        return True
    return False


def _snapshot_needs_iframe_retry(raw: str) -> bool:
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped in ("- insertion", "- iframe"):
            if not _tree_node_has_children(lines, index):
                return True
            continue
        iframe_match = _IFRAME_REF_LINE_RE.match(line.rstrip())
        if iframe_match is not None and not _tree_node_has_children(lines, index):
            return True
    return False


async def _enrich_hollow_iframe_snapshots(
    page: Page,
    raw: str,
    *,
    depth: int | None,
    boxes: bool,
) -> tuple[str, bool, int]:
    lines = raw.splitlines()
    result_lines: list[str] = []
    did_enrich = False
    unavailable_count = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        iframe_match = _IFRAME_REF_LINE_RE.match(line.rstrip())
        if iframe_match is None or _tree_node_has_children(lines, index):
            result_lines.append(line)
            index += 1
            continue

        iframe_ref = iframe_match.group(2)
        parent_indent = len(iframe_match.group(1))
        try:
            scoped = await ref_locator(page, iframe_ref).aria_snapshot(
                mode="ai",
                depth=depth,
                boxes=boxes,
            )
        except Exception:
            unavailable_count += 1
            trimmed = line.rstrip()
            if _IFRAME_UNAVAILABLE_SUFFIX not in trimmed:
                trimmed += _IFRAME_UNAVAILABLE_SUFFIX
            result_lines.append(trimmed)
            index += 1
            continue

        scoped_lines = [entry for entry in scoped.splitlines() if entry.strip()]
        if not scoped_lines:
            unavailable_count += 1
            trimmed = line.rstrip()
            if _IFRAME_UNAVAILABLE_SUFFIX not in trimmed:
                trimmed += _IFRAME_UNAVAILABLE_SUFFIX
            result_lines.append(trimmed)
            index += 1
            continue

        did_enrich = True
        trimmed = line.rstrip()
        if not trimmed.endswith(":"):
            trimmed += ":"
        result_lines.append(trimmed)

        child_prefix = " " * (parent_indent + 2)
        for scoped_line in scoped_lines:
            stripped = scoped_line.lstrip()
            if stripped.startswith("- "):
                result_lines.append(f"{child_prefix}{stripped}")
            else:
                result_lines.append(f"{child_prefix}- {stripped}")
        index += 1

    return "\n".join(result_lines), did_enrich, unavailable_count


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
        await page.aria_snapshot(mode="ai")
        tree = compress_snapshot(
            raw,
            include_urls=include_urls,
            max_url_len=max_url_len,
        )
        return await apply_snapshot_postprocessing(
            page,
            tree,
            snapshot_format=snapshot_format,
        )

    settings = get_snapshot_settings()
    raw = await page.aria_snapshot(mode="ai", depth=depth, boxes=boxes)
    for _ in range(settings.iframe_retry_count):
        if not _snapshot_needs_iframe_retry(raw):
            break
        await asyncio.sleep(settings.iframe_retry_delay_s)
        raw = await page.aria_snapshot(mode="ai", depth=depth, boxes=boxes)

    enriched, did_enrich, _iframe_unavailable = await _enrich_hollow_iframe_snapshots(
        page,
        raw,
        depth=depth,
        boxes=boxes,
    )
    if did_enrich:
        raw = enriched
        await page.aria_snapshot(mode="ai")
    tree = compress_snapshot(
        raw,
        include_urls=include_urls,
        max_url_len=max_url_len,
    )
    return await apply_snapshot_postprocessing(
        page,
        tree,
        snapshot_format=snapshot_format,
    )


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
    page_signals = await read_page_signals(page)
    snapshot = await capture_page_snapshot(
        page,
        ref=normalized_scope_ref,
        depth=depth,
        boxes=boxes,
        include_urls=include_urls,
        max_url_len=max_url_len,
        snapshot_format="tree",
    )
    return {
        "page_id": page_id,
        "url": page.url,
        "title": await page.title(),
        "scope_ref": normalized_scope_ref,
        "signals": {
            "dialog_count": page_signals["dialog_count"],
            "iframe_hollow_count": snapshot.count(_IFRAME_UNAVAILABLE_SUFFIX),
        },
        "snapshot": snapshot,
        **extra,
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
    locator = await resolve_ref_locator(page, normalized)

    subtree = await capture_tree_snapshot(
        page,
        ref=normalized,
        depth=depth,
        include_urls=include_urls,
        max_url_len=max_url_len,
    )
    headline = next((line for line in subtree.splitlines() if line.strip()), "")
    parsed = parse_node_headline(headline)
    role = await resolve_ref_role(page, normalized, fallback_role=parsed["role"])

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
        "role": role,
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
