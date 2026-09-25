#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Word retrieval directly from the existing FTS5 indexes (no duplicate corpus)."""
import json
import uuid

from .database import timestamp
from .retrieval import UNTRUSTED, filters


def word_token(db, value):
    """Let the same unicode61 tokenizer used by history define a word."""
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ValueError("A word must contain 1–512 characters")
    db.execute("CREATE VIRTUAL TABLE temp.query_tokens USING fts5(content, tokenize='unicode61 remove_diacritics 2')")
    db.execute("CREATE VIRTUAL TABLE temp.query_vocab USING fts5vocab(query_tokens, instance)")
    db.execute("INSERT INTO query_tokens(content) VALUES(?)", (value,))
    tokens = db.execute("SELECT term FROM query_vocab ORDER BY offset").fetchall()
    if len(tokens) != 1:
        raise ValueError("Supply exactly one word; use recall with mode=phrase for phrases")
    db.execute("DROP TABLE IF EXISTS temp.query_tokens")
    db.execute("DROP TABLE IF EXISTS temp.query_vocab")
    return tokens[0][0]


def vocabulary(db, scope, options, *, term=None, prefix=None):
    if scope not in ("history", "memories", "all"):
        raise ValueError("Scope must be history, memories or all")
    queries, parameters = [], []
    for kind, table, index in (("history", "messages", "message_fts"),
                               ("memories", "memories", "memory_fts")):
        if scope not in (kind, "all"):
            continue
        vocab = index + "_instances"
        db.execute(f"CREATE VIRTUAL TABLE temp.{vocab} USING fts5vocab(main, {index}, instance)")
        where, values = filters(kind, **options)
        if kind == "history":
            visible = "m.role IN ('user','assistant') AND m.status='completed'"
            metadata = "m.session_id,m.role,m.sequence,m.source_ref"
        else:
            visible = "m.status='active' AND (m.expires_at IS NULL OR m.expires_at > ?)"
            parameters.append(timestamp())
            metadata = "NULL AS session_id,NULL AS role,NULL AS sequence,NULL AS source_ref"
        parameters.extend(values)
        if term is not None:
            where += " AND v.term=?"
            parameters.append(term)
        if prefix is not None:
            # Range constraint lets fts5vocab seek instead of scanning every term.
            where += " AND v.term >= ? AND v.term < ?"
            parameters.extend((prefix, prefix + chr(0x10ffff)))
        queries.append(f"""SELECT v.term,m.id,m.rowid AS document_rowid,v.offset AS token_index,
            '{kind}' AS source_type,m.created_at,{metadata}
            FROM {vocab} v JOIN {table} m ON m.rowid=v.doc
            WHERE {visible} {where}""")
    return " UNION ALL ".join(queries), parameters


def page(rows, *, key, offset, total, max_chars, **metadata):
    """Return a contiguous page; budget omissions must remain reachable."""
    result = {"warning": UNTRUSTED, **metadata, key: [], "total": total,
              "next_offset": offset if total > offset else None}
    for row in rows:
        candidate = {**result, key: result[key] + [row],
                     "next_offset": offset + len(result[key]) + 1}
        if len(json.dumps(candidate, ensure_ascii=False)) > max_chars - 16:
            break
        result = candidate
    if offset + len(result[key]) >= total:
        result["next_offset"] = None
    if rows and not result[key]:
        raise ValueError("Result metadata exceeds recall_chars; increase the configured budget")
    return result


def search_words(db, prefix, *, scope, options, limit, offset, max_chars):
    normalized = word_token(db, prefix) if prefix else None
    query, values = vocabulary(db, scope, options, prefix=normalized)
    grouped = f"""SELECT term AS word,COUNT(*) AS occurrences,
        COUNT(DISTINCT source_type || ':' || id) AS documents
        FROM ({query}) GROUP BY term"""
    total = db.execute(f"SELECT COUNT(*) FROM ({grouped})", values).fetchone()[0]
    rows = [dict(row) for row in db.execute(
        grouped + " ORDER BY word LIMIT ? OFFSET ?", (*values, limit, offset))]
    return page(rows, key="words", offset=offset, total=total, max_chars=max_chars, scope=scope)


def match_spans(highlighted, opening, closing):
    """Convert SQLite highlights into offsets in the original Python string."""
    cursor = position = 0
    while (start := highlighted.find(opening, cursor)) >= 0:
        position += start - cursor
        end = highlighted.index(closing, start + len(opening))
        length = end - start - len(opening)
        yield position, position + length
        position += length
        cursor = end + len(closing)


def word_instances(db, word, *, scope, options, limit, offset, max_chars):
    term = word_token(db, word)
    query, values = vocabulary(db, scope, options, term=term)
    total = db.execute(f"SELECT COUNT(*) FROM ({query})", values).fetchone()[0]
    rows = [dict(row) for row in db.execute(
        f"SELECT * FROM ({query}) ORDER BY created_at DESC,source_type,id,token_index LIMIT ? OFFSET ?",
        (*values, limit, offset))]
    cache = {}
    for row in rows:
        key = (row["source_type"], row.pop("document_rowid"))
        if key not in cache:
            index = "message_fts" if key[0] == "history" else "memory_fts"
            original = db.execute(f"SELECT content FROM {index} WHERE rowid=?", (key[1],)).fetchone()[0]
            marker = uuid.uuid4().hex
            while marker in original:
                marker = uuid.uuid4().hex
            opening, closing = "<" + marker + ">", "</" + marker + ">"
            highlighted = db.execute(
                f"SELECT highlight({index},0,?,?) FROM {index} WHERE rowid=? AND {index} MATCH ?",
                (opening, closing, key[1], '"' + term.replace('"', '""') + '"')).fetchone()[0]
            offsets = [item[0] for item in db.execute(
                f"SELECT offset FROM {index}_instances WHERE doc=? AND term=? ORDER BY offset",
                (key[1], term))]
            spans = list(match_spans(highlighted, opening, closing))
            if len(offsets) != len(spans):
                raise RuntimeError("FTS word positions and highlights disagree")
            cache[key] = original, dict(zip(offsets, spans))
        original, spans = cache[key]
        start, end = spans[row["token_index"]]
        excerpt_start, excerpt_end = max(0, start - 80), min(len(original), end + 80)
        row.update(word=term, start=start, end=end, matched_text=original[start:end],
                   excerpt=original[excerpt_start:excerpt_end], excerpt_start=excerpt_start,
                   truncated=excerpt_start > 0 or excerpt_end < len(original))
        row.pop("term")
    return page(rows, key="instances", offset=offset, total=total, max_chars=max_chars,
                word=term, scope=scope)
