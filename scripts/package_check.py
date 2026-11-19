#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


def inspect_package(root):
    errors = []
    warnings = []
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("Package root is not a directory")
    files = []
    for path in root.rglob("*"):
        if path.is_symlink():
            errors.append(f"Symlink is forbidden: {path.relative_to(root)}")
            continue
        if path.is_file():
            files.append(path)
    if len(files) > 50:
        errors.append(f"Too many files: {len(files)} > 50")
    total = sum(path.stat().st_size for path in files)
    if total > 2 * 1024 * 1024:
        errors.append(f"Package exceeds 2 MiB: {total}")
    for path in files:
        size = path.stat().st_size
        relative = path.relative_to(root)
        if size > 500 * 1024:
            errors.append(f"File exceeds 500 KiB: {relative}")
        try:
            path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, UnicodeError):
            errors.append(f"File is not UTF-8: {relative}")
    skill = root / "SKILL.md"
    if not skill.is_file():
        errors.append("Missing SKILL.md")
    else:
        text = skill.read_text(encoding="utf-8")
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---" or "---" not in lines[1:]:
            errors.append("SKILL.md must start with YAML frontmatter")
        else:
            end = lines[1:].index("---") + 1
            fields = {}
            for line in lines[1:end]:
                match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
                if match:
                    fields[match.group(1)] = match.group(2).strip()
            name = fields.get("name", "")
            description = fields.get("description", "")
            if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
                errors.append("Invalid frontmatter name")
            if not description or len(description) > 1024:
                errors.append("Description must contain 1..1024 characters")
            for key in fields:
                if key not in {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}:
                    warnings.append(f"Unrecognized frontmatter key: {key}")
        if len(lines) >= 500:
            errors.append("SKILL.md must be under 500 lines")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if "://" not in target and not (skill.parent / target).is_file():
                errors.append(f"Broken local link in SKILL.md: {target}")
    github = root / "GITHUB_URL.txt"
    if not github.is_file():
        warnings.append("No GITHUB_URL.txt; public-link bonus cannot be claimed")
    elif github.is_symlink():
        errors.append("GITHUB_URL.txt must not be a symlink")
    else:
        github_lines = github.read_text(encoding="utf-8").splitlines()
        if not github_lines or not re.match(r"^https://github\.com/[^/\s]+/[^/\s]+", github_lines[0]):
            errors.append("First GITHUB_URL.txt line must be a GitHub repository or directory URL")
    return {"valid": not errors, "root": str(root), "files": len(files),
            "bytes": total, "errors": errors, "warnings": warnings}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check the Skill text-package limits")
    parser.add_argument("root")
    args = parser.parse_args()
    try:
        report = inspect_package(args.root)
    except (OSError, ValueError) as error:
        report = {"valid": False, "errors": [str(error)], "warnings": []}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["valid"] else 1)
