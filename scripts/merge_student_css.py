"""Merge all student-specific CSS files into a single consolidated student.css.

Cascade order (matches original loading order in templates/sidebar):
1. student.css (current base: tasks, logbook, profile, classwork, task/session details)
2. student-workspace.css (shared workspace + design tokens)
3. student-shell-fix.css (shell normalization)
4. student-theme-fix.css (documents/notifications page frame)
5. student-page-header.css (canonical heading normalization)
6. student-sidebar-collapse-fix.css (collapsed icon-only sidebar)
7. student-notification-popover.css (notification bell/popover)
8. student-dashboard.css (full dashboard page styling)
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = ROOT / "resources" / "assets" / "css"

# Files in cascade order (later files win on conflicts)
SOURCES = [
    ("student-workspace.css",        "Shared Workspace + Design Tokens"),
    ("student-shell-fix.css",        "Shell Normalization"),
    ("student-theme-fix.css",        "Documents/Notifications Page Frame"),
    ("student-page-header.css",      "Canonical Page Heading Normalization"),
    ("student-sidebar-collapse-fix.css", "Collapsed Icon-Only Sidebar"),
    ("student-notification-popover.css",  "Notification Bell/Popover"),
    ("student-dashboard.css",        "Student Dashboard Page"),
]

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def build() -> str:
    parts: list[str] = []

    # 1. Keep the current student.css as-is (already has tasks, logbook, profile, etc.)
    current = read(CSS_DIR / "student.css")
    parts.append(current)

    # 2-N. Append each source file with a section banner
    for filename, description in SOURCES:
        src = CSS_DIR / filename
        if not src.exists():
            print(f"  WARN: {filename} not found, skipping", file=sys.stderr)
            continue
        content = read(src)
        banner = (
            f"\n\n/* =========================================================\n"
            f"   Consolidated Student CSS — {description}\n"
            f"   Source: {filename}\n"
            f"   ========================================================= */\n\n"
        )
        parts.append(banner)
        parts.append(content)

    return "\n".join(parts)


def main():
    merged = build()
    target = CSS_DIR / "student.css"
    target.write_text(merged, encoding="utf-8")
    line_count = merged.count("\n") + 1
    byte_count = len(merged.encode("utf-8"))
    print(f"Consolidated student.css: {line_count} lines, {byte_count} bytes")


if __name__ == "__main__":
    main()
