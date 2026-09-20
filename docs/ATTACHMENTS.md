# Desktop Attachments

The PySide6 interface allows users to select multiple files through the native file picker, remove them individually, and send text, files, or both. The paperclip button shares the Send button's styling. Attachment cards support horizontal scrolling; in smaller windows, the chat area can scroll to keep the message composer accessible.

`Attachment` and `DesktopMessage` are immutable dataclasses. Initial validation runs in a `QThreadPool`; the existing worker rechecks file accessibility, size, and modification time before accepting the request. The draft is preserved until that acceptance is received. Any subsequent model or TTS failure occurs after the request has already been accepted. Removing an attachment card never deletes the original file.

Files are accessed directly from their original locations; they are not copied to temporary directories. Files cannot be modified between selection and reading. If a file changes, it must be attached again to accept its updated version.

## Agent Access
Each execution receives a JSON metadata manifest and a temporary `read_attachment` tool. File contents are not automatically injected into the model's context.
Small files can be read in a single call, while larger files are read in chunks using `next_offset`, `partial`, and `has_more`. The cache exists only for the duration of the request. `read_file` also enforces these limits when accessing an active attachment.
Tools do not execute attached files or treat their contents as system instructions. Logs record message text, filenames, and file paths without automatically including file contents.
Attachments remain available for the duration of the submitted request; they are not stored permanently across turns. To ask another question about unread portions of a file, attach it again. Previously retrieved chunks remain part of the normal conversation history.
## Supported Formats and Limits
- UTF-8, UTF-16 with BOM, and Windows-1252 text; source code, Markdown, JSON, XML, YAML, CSV/TSV, and common configuration formats. Empty files, binary content, and unsupported formats are rejected.
- PDF: Page-by-page text extraction **only if `pypdf` is installed**. It is neither installed automatically nor required for other functionality. OCR and encrypted PDFs are not supported. `pypdf` is not installed in the current development environment.
- PNG, JPEG, WebP, and GIF: Visual input through PydanticAI's `BinaryContent`, only when Ollama's `/api/show` confirms the `vision` capability. If vision support cannot be confirmed, image submission is rejected and the draft is preserved. GIF animation analysis is not guaranteed. Image processing also consumes the context budget.
The following values can be configured in the `attachments` object in `~/.arlo/json/config.json`, including through `update_config`:

```json
{
  "attachments": {
    "max_files": 10,
    "max_file_bytes": 20971520,
    "max_total_bytes": 52428800,
    "chunk_bytes": 4096,
    "context_bytes": 8192,
    "max_image_pixels": 1048576
  }
}
```
The per-request content budget is limited to the smaller of `context_bytes` and one-quarter of Ollama's context window.
The active context window is retrieved from `/api/ps`, followed by `num_ctx` from `/api/show`, with a conservative fallback of 4,096 tokens. Additional space is reserved based on the previous turn's actual token usage, the metadata manifest, and the response.
Repeated reads do not access the disk again, but they still consume the context budget if their contents are reintroduced into the model's context.
When the budget is exhausted, the tool explicitly reports the limit, and the agent must request a narrower scope.
This limits the amount of context added by attachments: Ollama does not provide advance token counting through the adapter currently in use, and the existing conversation history management is not replaced.
All processing and model requests remain on localhost.

## Verification
```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```
Interface tests use Qt's offscreen mode and mock the native file dialog and service startup.
PydanticAI tests exercise real file-reading tools with a controlled model, including desktop streaming.
The tests do not require Ollama, TTS, or Steam to be running, and they do not write to the user's logs.

## Voice
Fixed a normalization bug that passed empty text to `split_paragraph`, causing an `IndexError`. Chunks containing no letters or digits are now ignored by the service.
The client preserves asynchronous synthesis errors and detects 120 seconds without progress, reporting an unresponsive service instead of waiting indefinitely.
If a TTS process is already stuck, it must be restarted to restore voice functionality. Service changes take effect after restarting the service, while desktop changes take effect after reopening the application.