"""Remove the leading module-level docstring from each file (keep function docstrings)."""
import ast
import glob
import sys


def strip(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    doc = ast.get_docstring(tree, clean=False)
    if doc is None or not tree.body:
        return False
    node = tree.body[0]
    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)):
        return False
    lines = src.splitlines(keepends=True)
    start = node.lineno - 1          # 0-based first line of docstring
    end = node.end_lineno           # 1-based last line -> slice end
    # drop the docstring lines
    rest = lines[:start] + lines[end:]
    text = "".join(rest).lstrip("\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


if __name__ == "__main__":
    files = []
    for d in ("core", "sources", "analytics", "render", "app"):
        files += glob.glob(d + "/*.py")
    files += ["bot.py"] + glob.glob("scripts/*.py")
    for fn in files:
        if "__init__" in fn:
            continue
        if strip(fn):
            print("stripped", fn)
