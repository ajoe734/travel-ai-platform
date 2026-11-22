#!/usr/bin/env python3
"""Validate imported source bytes, local documentation links and prototype syntax.

This is a repository integrity check. It does not execute a database, browser,
backend, payment provider or external connector.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


class InlineScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self.external_scripts: list[str] = []
        self.current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        attributes = dict(attrs)
        if attributes.get("src"):
            self.external_scripts.append(str(attributes["src"]))
            self.current = None
        elif attributes.get("type", "") in ("", "text/javascript", "application/javascript", "module"):
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def validate() -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    report: dict = {"schema_version": 1, "scope": "source integrity, local links, JavaScript syntax"}
    manifest_path = ROOT / "docs/provenance/source-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
            raise ValueError("unsupported manifest format")
    except (OSError, ValueError) as exc:
        return {**report, "status": "failed", "errors": [f"Cannot read source manifest: {exc}"], "warnings": []}

    verified_sources = 0
    source_bytes = 0
    seen_paths: set[str] = set()
    for entry in manifest["files"]:
        path = (ROOT / entry["path"]).resolve()
        if not path.is_relative_to(ROOT):
            errors.append(f"Source path escapes repository: {entry['path']}")
            continue
        if entry["path"] in seen_paths:
            errors.append(f"Duplicate source manifest path: {entry['path']}")
            continue
        seen_paths.add(entry["path"])
        if not path.is_file():
            errors.append(f"Missing original source: {entry['path']}")
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != entry["size"] or digest != entry["sha256"]:
            errors.append(f"Original source changed: {entry['path']}")
        else:
            verified_sources += 1
            source_bytes += len(data)

    extraction_path = ROOT / "docs/provenance/extraction-report.json"
    if not extraction_path.is_file():
        errors.append("Missing Word extraction report")

    # Code samples and historical paths are documentation, not active links.
    link_pattern = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)")
    local_links = 0
    markdown_files = sorted(p for p in ROOT.rglob("*.md") if ".git" not in p.parts)
    for source in markdown_files:
        text = source.read_text(encoding="utf-8")
        text = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1\s*$", "", text)
        for match in link_pattern.finditer(text):
            url = match.group(1).strip().split(' "', 1)[0].strip("<>")
            parts = urlsplit(url)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            target = (source.parent / unquote(parts.path)).resolve()
            local_links += 1
            if not target.is_relative_to(ROOT):
                errors.append(f"Local link escapes repository in {relative(source)}: {url}")
            elif not target.exists():
                errors.append(f"Broken local link in {relative(source)}: {url}")

    required_paths = [
        "AGENTS.md", "docs/README.md", "docs/project/current-decisions.md",
        "docs/sd/README.md", "docs/sd/sa-v1-gaps.md",
        "docs/sd/work-execution-contract.md", "docs/sd/authorization-and-approval.md",
        "docs/sd/connector-result-and-reconciliation.md", "docs/sd/credit-and-refund.md",
        "docs/collaboration/herdr-handoff.md", "docs/collaboration/backlog.md",
        "docs/verification/prototype-audit.md", "specs/README.md",
        "prototypes/merchant-assistant/ux-v2.1/index.html",
    ]
    for path in required_paths:
        if not (ROOT / path).is_file():
            errors.append(f"Missing required entry: {path}")

    node = shutil.which("node")
    syntax_checks = []
    with tempfile.TemporaryDirectory(prefix="travel-validate-") as tmp:
        for html_path in sorted((ROOT / "prototypes").rglob("*.html")):
            parser = InlineScripts()
            parser.feed(html_path.read_text(encoding="utf-8"))
            if parser.external_scripts:
                warnings.append(f"External scripts require separate review: {relative(html_path)}")
            for index, script in enumerate(parser.scripts):
                item = {"path": relative(html_path), "script_index": index}
                if node:
                    js_path = Path(tmp) / f"script-{len(syntax_checks)}.js"
                    js_path.write_text(script, encoding="utf-8")
                    check = subprocess.run([node, "--check", str(js_path)], capture_output=True, text=True, timeout=30)
                    item["status"] = "passed" if check.returncode == 0 else "failed"
                    if check.returncode:
                        errors.append(f"JavaScript syntax failed: {relative(html_path)} script {index}: {check.stderr[:400]}")
                else:
                    item["status"] = "not_run_node_unavailable"
                syntax_checks.append(item)
    if not node:
        warnings.append("Node.js is unavailable; JavaScript syntax checks were not run.")

    report.update(
        status="failed" if errors else "passed",
        source_files_verified=verified_sources,
        source_bytes_verified=source_bytes,
        markdown_files_checked=len(markdown_files),
        local_links_checked=local_links,
        javascript_syntax_checks=syntax_checks,
        errors=errors,
        warnings=warnings,
        not_tested=["real browser UI and accessibility", "database migrations", "backend integration", "external providers", "production deployment"],
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the validation report as JSON")
    args = parser.parse_args()
    report = validate()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Repository checks: {report['status']}")
        print(f"Original files verified: {report.get('source_files_verified', 0)}")
        print(f"Local documentation links checked: {report.get('local_links_checked', 0)}")
        print(f"JavaScript scripts checked: {len(report.get('javascript_syntax_checks', []))}")
        for error in report["errors"]:
            print(f"ERROR: {error}")
        for warning in report["warnings"]:
            print(f"NOTE: {warning}")
        print("These checks do not verify a production application or external integration.")
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
