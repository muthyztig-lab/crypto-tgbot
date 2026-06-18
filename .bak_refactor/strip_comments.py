"""Strip noise comments while keeping docstrings, strings and functional comments."""
import io
import re
import sys
import tokenize

KEEP = re.compile(r"#!|coding[:=]|\bnoqa\b|\btype:\s*ignore|\btype:|\bpragma\b", re.I)


def strip_file(path):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    lines = src.splitlines(keepends=True)
    # Collect comment tokens to drop (row -> col where comment starts).
    drops = {}
    try:
        toks = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in toks:
            if tok.type == tokenize.COMMENT and not KEEP.search(tok.string):
                row = tok.start[0]
                col = tok.start[1]
                # keep the earliest comment col on a line (full-line vs trailing)
                drops[row] = min(col, drops.get(row, col))
    except tokenize.TokenError:
        pass

    out = []
    for i, line in enumerate(lines, start=1):
        if i in drops:
            col = drops[i]
            before = line[:col]
            if before.strip() == "":
                # full-line comment -> drop line entirely
                continue
            # trailing comment -> keep code, drop comment
            out.append(before.rstrip() + "\n")
        else:
            out.append(line)

    text = "".join(out)
    # collapse 3+ blank lines into 2
    text = re.sub(r"\n{3,}", "\n\n\n", text)
    # trim leading blank lines
    text = text.lstrip("\n")
    # ensure single trailing newline
    text = text.rstrip("\n") + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        strip_file(p)
        print("stripped", p)
