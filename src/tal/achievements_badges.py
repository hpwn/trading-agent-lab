"""Utilities to generate README badge rows for achievements."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast
from urllib.parse import quote

from tal import achievements

Style = Literal["flat", "flat-square", "for-the-badge"]
LabelCase = Literal["lower", "title"]

MARKER_START = "<!-- ACHIEVEMENTS:START -->"
MARKER_END = "<!-- ACHIEVEMENTS:END -->"


class BadgeKeyError(ValueError):
    """Raised when an unexpected badge key format is encountered."""


def _parse_badge_key(key: str) -> tuple[str, str, str]:
    """Return mode, threshold, and kind parsed from a badge key."""

    delimiter = "_first_$"
    if delimiter not in key:
        raise BadgeKeyError(f"Invalid badge key: {key}")
    mode, remainder = key.split(delimiter, 1)
    try:
        threshold, kind = remainder.rsplit("_", 1)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise BadgeKeyError(f"Invalid badge key: {key}") from exc
    return mode, threshold, kind


def _apply_label_case(label: str, label_case: LabelCase) -> str:
    if label_case == "lower":
        return label.lower()
    if label_case == "title":
        return label.title()
    raise ValueError(f"Unsupported label case: {label_case}")


def _validate_style(style: str) -> Style:
    allowed: tuple[Style, ...] = ("flat", "flat-square", "for-the-badge")
    if style not in allowed:
        raise ValueError(f"Unsupported badge style: {style}")
    return cast(Style, style)


def _build_label(mode: str, threshold: str, kind: str, label_case: LabelCase) -> str:
    label = f"{mode} ${threshold} {kind}"
    return _apply_label_case(label, label_case)


def _url(label: str, status: str, color: str, *, style: Style) -> str:
    encoded_label = quote(label, safe="")
    return (
        "https://img.shields.io/badge/"
        f"{encoded_label}-{status}-{color}?style={style}"
    )


def _badge_markdown(
    key: str,
    *,
    style: Style,
    label_case: LabelCase,
    emojis: bool,
) -> str:
    mode, threshold, kind = _parse_badge_key(key)
    label = _build_label(mode, threshold, kind, label_case)
    unlocked = achievements.is_unlocked(key)
    status = "unlocked" if unlocked else "locked"
    color = "success" if unlocked else "lightgrey"

    def _label(base: str) -> str:
        if emojis:
            suffix = "🔓" if unlocked else "🔒"
            return f"{base} {suffix}"
        return base

    label_with_suffix = _label(label)
    alt_text = (
        label_with_suffix.title() if label_case == "lower" else label_with_suffix
    )
    return f"![{alt_text}]({ _url(label_with_suffix, status, color, style=style) })"


def render_badges_line(
    *,
    style: Style = "flat-square",
    label_case: LabelCase = "lower",
    emojis: bool = False,
) -> str:
    """Render all planned badges as a single Markdown line."""

    validated_style = _validate_style(style)
    badges = [
        _badge_markdown(
            key,
            style=validated_style,
            label_case=label_case,
            emojis=emojis,
        )
        for key in achievements.all_planned_badge_keys()
    ]
    return " ".join(badges)


def update_readme(path: Path | str, badges_line: str) -> bool:
    """Update README markers with the provided badge line."""

    readme_path = Path(path)
    if not readme_path.exists():
        return False
    content = readme_path.read_text(encoding="utf-8")
    if MARKER_START in content and MARKER_END in content:
        prefix, remainder = content.split(MARKER_START, 1)
        _, suffix = remainder.split(MARKER_END, 1)
        new_content = (
            f"{prefix}{MARKER_START}\n{badges_line}\n{MARKER_END}{suffix}"
        )
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        new_content = (
            f"{content}\n## Achievements\n{MARKER_START}\n"
            f"{badges_line}\n{MARKER_END}\n"
        )
    readme_path.write_text(new_content, encoding="utf-8")
    return True


__all__ = [
    "MARKER_END",
    "MARKER_START",
    "BadgeKeyError",
    "render_badges_line",
    "update_readme",
]
