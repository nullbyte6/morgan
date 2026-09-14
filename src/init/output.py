"""Plain terminal formatting for model responses."""

import re


def chunks_group(chunks):
    """Remove paired bold markers, including those split across stream chunks.
    Buffer one line so unmatched asterisks and literal code remain intact.
    """
    pending = ""
    fence = None

    def clean_line(line):
        nonlocal fence
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            return line
        if fence is not None:
            return line
        parts = re.split(r"(`+[^`]*`+)", line)
        for index in range(0, len(parts), 2):
            parts[index] = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"\1", parts[index])
        return "".join(parts)

    for chunk in chunks:
        pending += chunk
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            yield clean_line(line + "\n")
    if pending:
        yield clean_line(pending)
