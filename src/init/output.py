"""Plain terminal formatting for model responses."""

import re


_COURTESY_QUESTION = re.compile(
    r"¿?(?:"
    r"how (?:can|may) I (?:assist|help) you(?: (?:now|today|further))?"
    r"|(?:is there )?anything else(?: (?:I can (?:help|assist) you with|you need(?: help with)?))?"
    r"|(?:do you|would you like|can I offer) (?:need )?(?:any |more |further )?(?:help|assistance)"
    r"|(?:en |con )?qu[ée] (?:m[áa]s )?(?:puedo ayudarte|te puedo ayudar)(?: (?:ahora|hoy))?"
    r"|c[óo]mo puedo ayudarte(?: (?:ahora|hoy))?"
    r"|(?:hay )?algo m[áa]s(?: (?:en lo que|con lo que) (?:pueda ayudarte|te pueda ayudar|necesites ayuda))?"
    r"|necesitas (?:algo m[áa]s|(?:m[áa]s )?ayuda)"
    r"|(?:puedo ayudarte|te puedo ayudar) (?:en|con) algo m[áa]s"
    r"|(?:is there )?anything else I can (?:help|assist) with"
    r"|hay alguna (?:otra )?aplicaci[óo]n espec[íi]fica de la que necesites informaci[óo]n"
    r")\?", re.IGNORECASE,
)


def remove_courtesy_questions(text):
    """Drop standalone generic help questions, leaving task clarifications intact."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [sentence for sentence in sentences
            if not _COURTESY_QUESTION.fullmatch(sentence.strip())]
    if len(kept) == len(sentences):
        return text
    return " ".join(kept) + ("\n" if kept and text.endswith("\n") else "")


def plain_text_chunks(chunks):
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
        # Keep inline code (including Python's ** operator) verbatim.
        parts = re.split(r"(`+[^`]*`+)", line)
        for index in range(0, len(parts), 2):
            parts[index] = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"\1", parts[index])
            parts[index] = remove_courtesy_questions(parts[index])
        return "".join(parts)

    for chunk in chunks:
        pending += chunk
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            yield clean_line(line + "\n")
    if pending:
        yield clean_line(pending)
