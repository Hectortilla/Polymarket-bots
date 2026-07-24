#!/usr/bin/env python3
"""Audit the structural completeness of Markdown C4 documentation."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


VIEW_PATTERNS = {
    "system-landscape": re.compile(r"\bsystem[\s-]+landscape\b", re.IGNORECASE),
    "system-context": re.compile(r"\bsystem[\s-]+context\b", re.IGNORECASE),
    "container": re.compile(r"\bcontainers?\b", re.IGNORECASE),
    "component": re.compile(r"\bcomponents?\b", re.IGNORECASE),
    "dynamic": re.compile(r"\bdynamic\b", re.IGNORECASE),
    "deployment": re.compile(r"\bdeployment\b", re.IGNORECASE),
    "code": re.compile(r"\bcode(?:-level)?\b", re.IGNORECASE),
}

REQUIRED_SECTIONS = {
    "scope": re.compile(r"^#{2,6}\s+scope\b", re.IGNORECASE | re.MULTILINE),
    "diagram": re.compile(r"^#{2,6}\s+diagram\b", re.IGNORECASE | re.MULTILINE),
    "key or legend": re.compile(
        r"^#{2,6}\s+(?:key|legend)\b", re.IGNORECASE | re.MULTILINE
    ),
    "evidence": re.compile(
        r"^#{2,6}\s+(?:evidence|sources?)\b", re.IGNORECASE | re.MULTILINE
    ),
    "assumptions or unknowns": re.compile(
        r"^#{2,6}\s+.*(?:assumptions?|unknowns?|limitations?|gaps?)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
}

DIAGRAM_FENCE = re.compile(
    r"```(?:mermaid|plantuml|puml|structurizr|dsl)\b", re.IGNORECASE
)
H1 = re.compile(r"^#\s+\S", re.MULTILINE)


@dataclass(frozen=True)
class Finding:
    severity: str
    path: Path
    message: str


def parse_expected(raw: str) -> set[str]:
    values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    unknown = values - VIEW_PATTERNS.keys()
    if unknown:
        choices = ", ".join(sorted(VIEW_PATTERNS))
        raise argparse.ArgumentTypeError(
            f"unknown expected view(s): {', '.join(sorted(unknown))}; choose from {choices}"
        )
    return values


def classify_view(path: Path, text: str) -> set[str]:
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_match.group(1) if title_match else ""
    sample = f"{path.stem.replace('_', ' ').replace('-', ' ')}\n{title}"
    return {name for name, pattern in VIEW_PATTERNS.items() if pattern.search(sample)}


def audit_document(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    if not H1.search(text):
        findings.append(Finding("ERROR", path, "missing level-1 title"))

    for label, pattern in REQUIRED_SECTIONS.items():
        if not pattern.search(text):
            findings.append(Finding("ERROR", path, f"missing '{label}' section"))

    if not DIAGRAM_FENCE.search(text):
        findings.append(
            Finding(
                "ERROR",
                path,
                "missing Mermaid, PlantUML, or Structurizr diagram source fence",
            )
        )

    if text.count("```") % 2:
        findings.append(Finding("ERROR", path, "unbalanced fenced code block"))

    if re.search(r"\b(?:TODO|FIXME|TBC)\b", text, re.IGNORECASE):
        findings.append(Finding("WARN", path, "contains unresolved placeholder text"))

    if not re.search(r"\b(?:verified|corroborated|assumed|unknown)\b", text, re.IGNORECASE):
        findings.append(
            Finding("WARN", path, "does not state evidence confidence or uncertainty")
        )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Markdown C4 diagram documents for required structure."
    )
    parser.add_argument("docs_dir", type=Path, help="C4 documentation directory")
    parser.add_argument(
        "--expect",
        type=parse_expected,
        default=set(),
        help="comma-separated required views, e.g. system-context,container",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return a non-zero exit code for warnings as well as errors",
    )
    args = parser.parse_args()

    docs_dir = args.docs_dir.resolve()
    if not docs_dir.is_dir():
        print(f"ERROR: documentation directory does not exist: {docs_dir}")
        return 2

    markdown_files = sorted(docs_dir.rglob("*.md"))
    if not markdown_files:
        print(f"ERROR: no Markdown files found under {docs_dir}")
        return 2

    findings: list[Finding] = []
    discovered: set[str] = set()
    diagram_documents = 0

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        views = classify_view(path, text)
        if views and path.name.lower() not in {"readme.md", "index.md"}:
            discovered.update(views)
            diagram_documents += 1
            findings.extend(audit_document(path, text))

    for missing in sorted(args.expect - discovered):
        findings.append(
            Finding("ERROR", docs_dir, f"expected '{missing}' view was not found")
        )

    if diagram_documents == 0:
        findings.append(
            Finding("ERROR", docs_dir, "no C4 diagram documents were identified")
        )

    for finding in sorted(
        findings, key=lambda item: (item.severity != "ERROR", str(item.path), item.message)
    ):
        try:
            display_path = finding.path.relative_to(docs_dir)
        except ValueError:
            display_path = finding.path
        print(f"{finding.severity}: {display_path}: {finding.message}")

    errors = sum(item.severity == "ERROR" for item in findings)
    warnings = sum(item.severity == "WARN" for item in findings)
    print(
        f"Audited {len(markdown_files)} Markdown file(s), "
        f"{diagram_documents} diagram document(s): "
        f"{errors} error(s), {warnings} warning(s)."
    )

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
