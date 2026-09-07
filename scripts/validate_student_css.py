"""Robust CSS structural validation for consolidated student.css."""
from pathlib import Path
import re

CSS = Path("resources/assets/css/student.css").read_text(encoding="utf-8")

# Strip comments first so they don't confuse the tokenizer
no_comments = re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL)

opens = no_comments.count("{")
closes = no_comments.count("}")
print(f"Curly braces: {{ = {opens}, }} = {closes}, balanced = {opens == closes}")

# Parentheses balance (used in calc(), rgb(), var(), url(), etc.)
po = no_comments.count("(")
pc = no_comments.count(")")
print(f"Parentheses: ( = {po}, ) = {pc}, balanced = {po == pc}")

# Check we have no unclosed @media blocks: count @media blocks
media_blocks = len(re.findall(r"@media\s*[^{]*\{", no_comments))
print(f"Media query blocks: {media_blocks}")

# Verify key CSS features survived
KEY = [
    (":root {", "design tokens"),
    ("--student-bg", "bg var"),
    ("--student-card-shadow", "shadow var"),
    ("@media", "media queries"),
    (".student-dashboard-workspace", "dashboard workspace"),
    (".student-dashboard-mini-ring", "dashboard ring"),
    (".student-notification-popover", "notification popover"),
    (".nx-student-shell", "student shell"),
    (".nx-sidebar.nx-collapsed", "collapsed sidebar"),
    ("[data-label]::after", "tooltip"),
]
for needle, name in KEY:
    print(f"  [{'PASS' if needle in CSS else 'FAIL'}] {name}")

# Enforce that body-level selectors in the original files are present at least once
for sel in [".nx-student-shell {", "body.student-page {", "body.student-dashboard-page {"]:
    n = no_comments.count(sel)
    print(f"  {'PASS' if n >= 1 else 'FAIL'} selector {sel!r} count={n}")

print("\nCSS structural validation complete.")