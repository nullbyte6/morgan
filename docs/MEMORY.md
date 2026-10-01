# Persistent memory
Arlo stores local conversation history and explicitly requested long-term memories
in SQLite. It uses the existing Python environment, SQLite FTS5 and the existing
Pydantic AI/Ollama agent. There is no vector database, additional model, background
extraction job, cloud synchronization, telemetry or network memory endpoint.

Restart Arlo after updating. New non-private conversations are persisted by default.
Existing Markdown logs are not automatically imported.

## Configuration and location
Configuration belongs in the existing `%USERPROFILE%\.arlo\json\config.json`:

```json
{
  "memory": {
    "enabled": true,
    "store_history": true,
    "database": "memory/memory.sqlite3",
    "max_results": 8,
    "context_chars": 4000,
    "recall_chars": 8000
  }
}
```

Relative database paths resolve under Arlo's user-data directory, independently
of the agent's working directory. The default is
`%USERPROFILE%\.arlo\memory\memory.sqlite3`. An absolute local path is supported;
UNC paths and relative parent traversal are rejected. Use a local disk, not a
network drive or a folder synchronized by third-party software. Changing the path
selects another database; it does not move or merge existing data.

`enabled=false` disables new memory writes, memory tools and injected memory
context, without deleting anything. `store_history=false` stops new SQLite
conversation persistence while leaving explicit memories available. Markdown
logging remains governed by the existing logger and `/private` setting.

Limits are characters, not model tokens. `max_results` accepts 1–50;
`context_chars` accepts 512–32000; `recall_chars` accepts 1024–64000. Invalid
configuration follows the application's existing last-valid-settings behavior.

## Using memory

Examples:
- “Remember that I prefer Spanish responses.”
- “Recuerda que prefiero respuestas en español.”
- “What did we decide about the garden last time?”
- “Update that preference to English.”
- “Forget that preference.”

The agent receives `remember`, `recall`, `forget`, `list_memories`, `search_words`,
`word_instances`, `read_conversation`, and `read_memory_message`.
Mutations require a current user request beginning with an
English or Spanish remember/save/update/forget/delete imperative, optionally with
a polite prefix. This deliberately conservative guard rejects mutations requested
only by retrieved text. Unrecognized phrasings should be restated explicitly.
The model still resolves the intended fact and memory ID; ambiguous requests
should result in a clarification rather than guessing.

`remember` takes content, category (`preference`, `fact`, `project`, `goal`,
`other`), optional semantic key, optional existing memory ID, and optional
timezone-aware ISO expiration. Reuse keys such as `response_language`: replacing
the content under that key atomically supersedes its previous active value.
Updating an exact ID keeps that ID. If the new content or key already belongs to another active memory, that memory is superseded by the updated one. Normalized duplicate content is reused.
Different paraphrases without a shared key are not semantically deduplicated.

### Recovering conversations and word occurrences

After restarting Arlo, requests such as these use the same local memory store:

- “Busca la frase jardín azul en nuestras conversaciones.”
- “¿Cuántas veces dije café? Muéstrame cada aparición y su contexto.”
- “Busca palabras que empiecen por jard.”
- “Abre la conversación donde hablamos de eso y continúa leyendo.”

`recall` keeps its default `any` mode (any queried word), and accepts `all`
(every queried word) or `phrase` (consecutive tokens, preserving repetitions).
Phrase matching follows the existing case/accent-insensitive tokenizer; punctuation
is a separator, so it is not a byte-for-byte string search. FTS operators in user
input are treated as text, not executable query syntax.

`recall`, `search_words`, and `word_instances` accept `session_id`, `role`
(`user` or `assistant`), `since` (inclusive), and `until` (exclusive).
Dates must be timezone-aware ISO timestamps and are converted to UTC. Dates filter
the matched record's creation time. Session/role filters for memories use their
linked source messages; a manually saved memory with no such source cannot match
those filters. Paired dialogue accompanying a recall hit may fall outside the
filters so the answer retains its original question.

`search_words(prefix="", scope="history")` lists normalized words alphabetically,
with occurrence and document counts. A prefix, when provided, must tokenize as one
word. `word_instances(word, scope="history")` requires exactly one whole word and
returns each occurrence separately, including repetitions in one message. Both
accept `scope="memories"` for current memories or `scope="all"` for both stores.
Counts exclude system messages, incomplete/error responses, candidates, expired
and superseded memories. A history message and a memory derived from it are two
separate documents in `all`; counts are lexical, not counts of distinct real events.

Each instance includes its source type and ID, original matched text, an excerpt,
zero-based `token_index`, and zero-based character `start`/`end` offsets (`end` is
exclusive). Character positions refer to Python Unicode characters in the original
text, not UTF-8 bytes or UTF-16 units. `excerpt_start` locates the excerpt within
that text. History hits additionally include session, role, sequence and source
reference. Instance order is newest record first, then source type, ID and position.

Word queries return an exact `total` for the selected scope and filters and a
`next_offset`. Pass it as `offset` to continue until null. Result pages respect
`max_results` and `recall_chars`, so they may contain fewer than `limit` items.
Pagination describes the database at each call; concurrent inserts/deletions can
shift later pages. Counts require visiting matching index entries; broad vocabulary
queries on very large archives cost more than a specific word or prefix query.

`read_conversation(session_id, after=0)` reads completed user/assistant dialogue
in sequence. Pass its `next_after` as `after` for subsequent pages. Open a clipped
message with `read_memory_message(message_id, offset=0)` and follow `next_offset`
to read every remaining character. Imported daily sessions still have unknown
original conversation boundaries. These tools use the same private-mode and
disabled-memory guards, and label all recovered text as untrusted evidence.

The maintenance CLI exposes the same read operations:

```powershell
.venv\Scripts\python.exe -B -m src.init.memory recall "jardín azul" --mode phrase
.venv\Scripts\python.exe -B -m src.init.memory words "jard" --scope all
.venv\Scripts\python.exe -B -m src.init.memory instances "café" --role user --limit 8
.venv\Scripts\python.exe -B -m src.init.memory conversation SESSION_ID --after 0
.venv\Scripts\python.exe -B -m src.init.memory message MESSAGE_ID --offset 0
```

Word retrieval uses connection-local `fts5vocab` views over the existing indexes
and SQLite's own tokenizer/highlights for exact positions. It needs no schema
migration, rebuild, extra dependency or copy of the corpus. Existing stored and
imported messages are immediately searchable. Original Markdown still needs the
explicit import described below. For the underlying index API see the
[SQLite FTS5 vocabulary documentation](https://www.sqlite.org/fts5.html#the_fts5vocab_virtual_table_module).

Only confirmed, explicit preferences are automatically injected, within the
configured count and character budgets. Other facts and old conversations are
retrieved on demand. The current session's Pydantic AI message history remains
separate and unchanged. Retrieved data is labelled untrusted and must never be
treated as instructions or permission to execute tools.

There is no automatic consolidation. The service can represent extracted items
as `candidate`, with confidence and provenance, for future development. Candidates
are excluded from normal retrieval and context until explicitly confirmed through
an update. Speculative extraction cannot supersede a confirmed memory.

## Architecture and public API
The implementation lives in `src/init/memory`:

| Component        | Responsibility                                                                       |
|------------------|--------------------------------------------------------------------------------------|
| `database.py`    | Connections, transactions, migrations, consistent backup                             |
| `service.py`     | Public `MemoryService` API, sessions/messages, memory lifecycle, import transactions |
| `retrieval.py`   | FTS queries, user/assistant pairing, bounded result formatting                       |
| `lexical.py`     | Indexed vocabulary, word instances, positions and paginated counts                   |
| `markdown.py`    | Conservative read-only parser of the existing daily logs                             |
| `integration.py` | Configuration, per-turn context, explicit-intent checks and instructions             |
| `tools.py`       | Pydantic AI-compatible tools; no direct SQL                                          |
| `__main__.py`    | Local maintenance CLI                                                                |

`MemoryService` exposes `start_session`, `end_session`, `get_session`,
`record_message`, `messages`, `remember`, `get_memory`, `update_memory`,
`delete_memory`, `list_memories`, `recall`, `context`, `delete_message`,
`search_words`, `word_instances`, `read_conversation`, `read_memory_message`,
`import_markdown`, `backup`, and `health`. `remember(..., supersedes=id)` supports
explicit replacement independently of a semantic key. The service is usable
without importing the desktop, agent tools, Ollama or TTS.

Both desktop and terminal already write through `SessionLog.write`; that remains
the single persistence entry point. SQLite stores normalized Markdown before
fenced code is replaced with archival links in the daily log. Accepted user
messages and finished assistant responses are recorded, and interrupted desktop
responses are marked `interrupted` and excluded from historical answer search.
Sessions without an end timestamp represent unclosed/interrupted sessions.

Initialization is lazy. Normal writes run on the existing assistant worker,
before or after a turn, never per generated token. Synchronous agent tools execute
through Pydantic AI's tool execution machinery. Short independent connections
avoid sharing a SQLite connection across threads; write lock waits are bounded at
500 ms. Database failures are logged under `arlo.memory`, exposed through
`SessionLog.memory_error`, and returned as unsuccessful tool results. Markdown
logging and current conversational state continue. A failed SQLite message write
can later be recovered through explicit log import.

Markdown and SQLite are separate stores, not one distributed transaction: a crash
after writing Markdown can leave a database gap. Byte-offset source identities
allow safe import of that gap without duplicating already persisted messages.

## Schema and search

Migrations run in one transaction and reject unknown newer or non-contiguous
schema versions. Version 1 creates `sessions`, `messages`, `memories`,
`memory_sources`, `imports`, and `deleted_sources`; version 2 adds FTS5 indexes
and maintenance triggers. `schema_migrations` records applied versions and times.

Messages have stable IDs, canonical roles, per-session sequence numbers,
timezone-aware timestamps, completion status and source references. Memories
have stable IDs, timestamps, optional expiry, category, semantic key, origin,
confidence and supersession linkage. Unique partial indexes prevent duplicate
active normalized contents and conflicting active keys. Source associations
survive message deletion with a null message ID and retained source reference.

Foreign keys are enabled on every connection, WAL allows concurrent readers,
and SQL values are parameterized. FTS5 is required; initialization reports a clear
error if the Python SQLite build lacks it. Ordinary chat can still use Markdown.

Search uses Unicode word tokens, accent-insensitive FTS5 matching and relevance
ranking. User input is quoted as literal terms, not accepted as raw FTS syntax.
Queries are limited to 512 characters and 32 distinct tokens. Search is lexical,
not semantic: use alternative words if synonyms do not match.

Historical hits contain session IDs, timestamps, stable message IDs and source
references. Assistant matches include the preceding user request; orphan
assistant responses are omitted. User matches include a following completed
assistant response when available. Results and excerpts are bounded, and clipped
content is marked `truncated`. Very small budgets can omit results whose metadata
and paired context do not fit. Only active, unexpired confirmed memories are
returned by normal memory retrieval.

## Historical Markdown import

Run from the repository root, supplying actual speaker names explicitly:
```powershell
.venv\Scripts\python.exe -B -m src.init.memory import "$env:USERPROFILE\.arlo\.log" --speaker "Diego=user" --speaker "Arlo=assistant" --speaker "System=system"
```

The command accepts individual files or directories of daily `.md` files.
It reports imported counts, warnings and errors as JSON. Use `--database PATH`
before the subcommand to operate on another database.

The parser accepts the actual `YYYY-MM-DD.md` format: the `Arlo Log — DATE`
header, `[HH:MM:SS ±HHMM]` lines, and following `Speaker: content` records.
It preserves filenames, byte offsets and known timestamps, supports UTF-8/BOM
and Windows CRLF, and ignores apparent message headers inside fenced code.
Unknown speakers, malformed timestamps and unrecognized headers are reported;
the parser never guesses a missing role or timestamp. Files over 16 MiB and
symbolic links are rejected. Archived code links are imported as links; linked
files are not followed or executed.

By default the final record is deferred because this format has no end marker.
A subsequent record seals it, allowing repeated incremental synchronization.
For a closed historical file, add `--include-tail` to accept its final record.
Do not use that option on a file Arlo is still writing. Unterminated fences remain
deferred even with this option. Previously imported prefixes are hashed; rewrites,
truncation, or changes to an already accepted record require manual review rather
than silently replacing history. Fix malformed inputs in a separate copy if
necessary; the importer never changes the originals.

Daily logs have no original session IDs. Each imported file receives a stable
synthetic session ID with metadata declaring the original boundaries unknown.
Pairing therefore means adjacent logged conversation, not a reconstructed actual
runtime session. Outside fenced code, a pasted passage that exactly mimics a log
record is inherently ambiguous; the legacy format cannot resolve it. Review
untrusted or edited files before importing. Distinct copies at different paths
are distinct sources. Re-importing the same path is idempotent.

## Privacy and deletion

`/private on` disables new Markdown and SQLite conversation writes, memory tools,
and injected memory context for private turns. It does not erase earlier logs,
backups or the current in-process conversation history. Turning it off resumes
normal behavior. Explicit memory writes reject common credential labels and
recognizable token/private-key formats. This heuristic is not a complete secret
scanner: do not submit secrets as memories. Ordinary conversation persistence
can contain whatever was spoken or typed, just as the existing Markdown logs can.

`forget(id)` permanently deletes that consolidated memory and its source links.
It does **not** delete its original conversation, previous superseded records,
Markdown files or backups. Historical recall may still find the original fact.
The local CLI provides separate scoped deletion:

```powershell
.venv\Scripts\python.exe -B -m src.init.memory delete-memory MEMORY_ID
.venv\Scripts\python.exe -B -m src.init.memory delete-message MESSAGE_ID
```

Message deletion removes its FTS visibility and records a source tombstone so
re-importing the same source cannot resurrect it. It leaves consolidated memories
and original Markdown untouched. Delete original logs separately when intended;
the memory service never deletes them. The existing Markdown logger's retention
policy remains unchanged; database history has no automatic retention purge.

SQLite is not encrypted by this feature. Protect the user profile and backups
with normal OS permissions and disk encryption as appropriate. `secure_delete`
is enabled for database operations, but deletion is a logical privacy operation,
not a guarantee of forensic erasure from FTS segments, WAL files, SSDs or backups.

## Backup, recovery and verification

```powershell
.venv\Scripts\python.exe -B -m src.init.memory check
.venv\Scripts\python.exe -B -m src.init.memory backup "D:\Backups\arlo-memory.sqlite3"
.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Backup uses SQLite's online backup API, includes committed WAL content and refuses
to overwrite an existing destination. Back up Markdown separately. For recovery,
stop all Arlo processes and maintenance commands, retain the damaged database and
its `-wal`/`-shm` companions for investigation, and select a verified backup copy
through `memory.database`. Run `check` on the restored copy before normal use.
Do not overwrite an open database or manually edit migration records. Missing
history can be recovered from original Markdown using the importer; consolidated
memories require a database backup or explicit recreation.

## Diary

Nova's **Diary** section presents the same database one day at a time, using local
time. For the selected day it shows what was on the agenda, the memories written or
updated that day, and each conversation with its time span and message count. Click a
conversation to unfold what was said. The arrows move one day, **Previous entry**
jumps to the closest earlier day with a conversation, and **Today** returns to the
present. The diary only reads: private conversations are never in it, nothing is sent
anywhere, and removing a memory still goes through a request to Arlo. With
`memory.enabled=false` the diary says that memory is off.

Tests use temporary databases and logs, including migration rollback, FTS,
concurrent writes, CRUD, supersession, deletion, imports, privacy, Pydantic AI tool
execution and the existing streamed agent lifecycle with a local test model.
They do not exercise a live Ollama model or physical microphone/TTS devices.
