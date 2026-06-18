"""Rewrite flat local imports to package-qualified imports."""
import glob
import re

PKG = {
    "config": "core", "settings": "core", "i18n": "core",
    "cache": "core", "db": "core", "storage": "core",
    "market_data": "sources", "onchain": "sources",
    "derivatives": "sources", "news": "sources",
    "analysis": "analytics", "indicators": "analytics", "signals": "analytics",
    "backtest": "analytics", "portfolio": "analytics", "ai": "analytics",
    "svg_render": "render", "pil_raster": "render", "cards": "render",
    "alerts": "app", "payments": "app", "ratelimit": "app",
}

from_re = re.compile(r"^(\s*)from (\w+)( import\b)")
import_re = re.compile(r"^(\s*)import (\w+)(\s+as\s+\w+)?\s*$")


def fix_line(line):
    m = from_re.match(line)
    if m and m.group(2) in PKG:
        mod = m.group(2)
        return f"{m.group(1)}from {PKG[mod]}.{mod}{m.group(3)}" + line[m.end():]
    m = import_re.match(line.rstrip("\n"))
    if m and m.group(2) in PKG:
        mod = m.group(2)
        alias = m.group(3) or ""
        return f"{m.group(1)}from {PKG[mod]} import {mod}{alias}\n"
    return line


def main():
    files = []
    for d in ("core", "sources", "analytics", "render", "app"):
        files += glob.glob(d + "/*.py")
    changed = 0
    for fn in files:
        with open(fn, encoding="utf-8") as f:
            lines = f.readlines()
        new = [fix_line(l) for l in lines]
        if new != lines:
            with open(fn, "w", encoding="utf-8") as f:
                f.writelines(new)
            changed += 1
    print(f"updated {changed} files")


if __name__ == "__main__":
    main()
