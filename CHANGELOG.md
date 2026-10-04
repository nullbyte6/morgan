# Changelog

All notable changes to Morgan, grouped by version with the most recent first. Entries inside each version are sorted alphabetically. Commits made before version 1.4.10-beta are grouped under Pre-1.4.10.

## 26.10.4-beta (2026-10-04)

- Add per-voice reference transcripts, a text file beside each voice's recorded clip, so every reference text matches what is said in its clip
- Fix the subtitles under the main Orb moving it up and down, by giving them a fixed three-line area where lines slide up on their own and wrap narrower to show more lines
- Update .gitignore to allow the voice transcript text files
- Update the CosyVoice instruction for non-default languages to leave out the language, accent and dialect, so the accent follows the spoken text instead of the hardcoded European Spanish, Simplified Chinese and Brazilian Portuguese names
- Update the Now playing workspace to replace the copy name and summarize buttons with two round icon buttons, copy that turns into a tick and a scroll, placed left of the playback controls, with the progress bar and playback controls moved to the bottom, tighter spacing between the song, artist and album, and a 15% larger cover
- Update the waveform icon on the send button to have 5 bars instead of 6

## 26.10.3-beta (2026-10-03)

- Add calculator to the command palette, opened by typing >> instead of >, that shows the result live as one types and copies it with Enter, covering arithmetic with exact fractions and decimals, implicit multiplication, factorials and mathematical functions and constants, equations such as x^2 = 4, unit conversions such as 5 km to mi and 20 degC to degF, and symbolic derivatives, integrals, limits, factoring, expansion and prime factorization computed on Enter, built on sympy and the new Pint dependency (with flexcache and flexparser) in requirements.txt, with its text in every interface language
- Add French, German, Portuguese (Brazil), Japanese, Russian, Korean and Italian as interface languages, selectable in Settings and the terminal version, with translated interface text, localized dates in Nova and wake word detection
- Add macOS desktop launching for the wake listener, opening Morgan.app when it is installed and the desktop entry from source otherwise
- Add macOS notifications, reminder dialogs with up to three buttons, and Spotify and Music now-playing, cover art, playback control and seeking through AppleScript to the macx64 package
- Add macOS window listing, app launching, quitting and hiding, mounted volumes, process termination, shutdown scheduling, installed apps, Trash emptying, Homebrew app management and the Steam folder to the macx64 package, with the pyobjc Cocoa and Quartz bindings it needs
- Add macx64 requirements, included from requirements.txt, with onnxruntime for the voice service on macOS in place of the Windows DirectML build
- Add natural speech rhythm, with random pauses between phrases, occasional hesitations such as "ehhh" and "uhmmm" in the language of the reply and occasional breaths, never while reading quotations, blockquotes or code verbatim; MORGAN_VOICE_NATURAL=0 disables it
- Add partial transcription of speech while the user pauses for half a second, so the transcript is usually ready when the end of voice input is detected
- Add per-turn voice latency log from the end of the user's speech to the first model text, the first phrase sent to speech and the first audible audio, with the first CosyVoice chunk and first played frame timed in the voice service
- Add platform layer with winx64 and macx64 packages behind a shared interface, moving window listing, launching, closing and minimizing, known folders, local drives and notifications out of the core so other operating systems can provide their own implementations
- Add scripts/arlo-services.sh, the macOS services launcher that starts Ollama, preloads the model, starts CosyVoice and opens a Terminal debug console following its logs, and run it at startup on macOS through the macx64 package
- Add scripts/build-dmg.sh, which builds Morgan.app with PyInstaller on an Apple Silicon Mac, with the app version and the microphone and automation permission prompts, and packs it into a build/installer/Morgan-<version>.dmg disk image
- Add scripts/build-tui-dmg.sh, which builds the terminal version on an Apple Silicon Mac and packs it with an Morgan Terminal.command launcher into a build/installer/MorganTUI-<version>.dmg disk image
- Add scripts/rebuild.sh, which builds both macOS disk images, stops at the first failure and opens build/installer
- Add themed native window frame with a title bar and resizable borders in place of the frameless transparent window, colored from the active theme with the dark or light title bar chosen from the theme, and a solid themed window background
- Add Toggle Morgan orb switch to Settings that turns off the floating orb, so closing the window sends Morgan to the system tray instead, remembered between sessions
- Fix Marina's voice cutting off while speaking, by fading out the end of her reference clip, which stopped abruptly, and adding silence after it
- Fix Morgan cutting itself off while speaking with the Marina voice and recording the end of its own speech as input, by keeping the echo reference for 1.5 seconds and requiring louder, longer sound to count as the user speaking while Morgan is talking
- Fix Morgan referring to itself with feminine forms whatever its name, by telling the model in the default identity prompt to take its gender from its name, masculine for male names and feminine for female ones
- Fix barge-in needing a loud, unbroken 0.6 seconds of sound while Morgan speaks, which made it work only when the user called out its name, by counting about one second of speech with short pauses between words as the user interrupting
- Fix barge-in needing a loud voice while Morgan speaks, by lowering the volume that counts as the user speaking over Morgan from 1200 to 900
- Fix every request failing on computers where Ollama was already running with its own small default context, by restarting Ollama at startup with the configured context length when the running server was started with a different one
- Fix image analysis always answering in Spanish unless asked otherwise, by answering in the interface language
- Fix installed copies failing to start their services, because the installer did not ship the platform layer that config.py and the voice service now import
- Fix installing from requirements.txt failing on torchcodec 0.1.2, a version that was never published, by pinning torchcodec 0.7.0, the release that matches the pinned torch and torchaudio 2.8
- Fix scripts\rebuild-tui.bat compiling the installer after a failed terminal build, by running build-tui.sh through Git's bash.exe so its exit code is checked
- Fix scripts\rebuild.bat only working from the scripts folder, compiling the installer after a failed build and never launching it, by running both builds through Git's bash.exe from the script's own folder, stopping at the first failure and starting the installer with start
- Fix speech of an interrupted response still being queued after the user interrupted it, by ignoring phrases that arrive after the turn was stopped
- Fix Morgan sometimes talking on after being stopped, by stopping the previous turn's speech whenever a new turn begins, targeting the last spoken turn on stop, stopping speech when a turn fails or its speech is disabled, and stopping even when the session no longer owns speech
- Fix splitting of Japanese text without kanji into phrases like English, which ignored the 。 sentence end and appended a stray period, by splitting any text with kana the Chinese way
- Fix splitting of spoken text leaving the closing » of a Russian quotation at the start of the next phrase, by keeping it with the sentence it closes
- Fix spoken file paths always spelling letters and the dot in Spanish, by using the letter names and the word for dot of the language detected in the reply for English, Spanish, Chinese, French, German, Portuguese, Italian, Russian, Japanese and Korean, and by keeping accented and non-Latin parts of a path that were dropped
- Fix the voice runtime on AMD ROCm installs failing to load audio, by installing TorchCodec 0.16 from PyPI after the ROCm PyTorch and the shared FFmpeg build it loads when only the static one is present, also repairing existing ROCm installs
- Renamed Arlo to Morgan as default name for The Assistant
- Update app installation, removal and residue scanning and the Steam library lookup to get winget commands, app data folders and the Steam folder from the platform layer
- Update Morgan to sound more relaxed and natural, with a relaxed conversational default tone, a response rule for everyday wording, and a slightly slower default speech speed
- Update the end of voice input to wait 1.8 seconds of silence instead of 0.6 to 1.2, so there is room to pause between words and sentences, including the wake silence default and its documentation
- Update source files to remove inline comments
- Update media session reading and playback control, the now-playing song reader and system audio capture for song recognition to go through the platform layer
- Update process termination, shutdown scheduling, installed application discovery, file opening and Recycle Bin emptying to go through the platform layer, so the core no longer requires winshell or winreg to import
- Update requirements.txt to keep only cross-platform dependencies and include the winx64 package's own requirements, so Windows-only libraries such as pywin32, winshell, winrt, pywinpty, DirectML and MKL install only on Windows
- Update responses to stream the model's text to the chat and to speech as it is generated, splitting the first spoken phrase at the first comma or sentence end, and falling back to complete responses if streaming fails or ARLO_VOICE_STREAMING is 0
- Update service startup, Ollama restarts, the updater and the voice service's priority and memory trimming to get the services script, installer, install location and process flags from the platform layer
- Update system diagnostics to run their PowerShell telemetry through the platform layer, keeping the allowed sources, result parsing and scoring in the core
- Update the built-in terminal, the TUI shell and the TUI file picker to get the pseudo-terminal, command injection, console encoding and drive list from the platform layer, moving the Windows Ctrl+C bootstrap and console input into winx64
- Update the config.json language check, the interface language table and the Settings and terminal language lists to cover every interface language
- Update the desktop window frame colors, popup anchoring, taskbar identity and the wake listener's launcher, priority and audio host to come from the platform layer
- Update the startup greeting, the week summary and the song summary to take the language name from one shared table, so they write in every interface language instead of falling back to English
- Update the terminal version's Nova day and month names, which were hardcoded for English, Spanish and Chinese, to cover every interface language, and the Nova calendar month titles to use the standalone month name that Russian requires
- Update the storage folder locator, file locks and elevated commands to get registry variables, msvcrt locks, administrator checks, the default shell and sudo from the platform layer
- Update the voice service to run a silent warm-up sentence when it starts, so the first spoken reply takes about 6 seconds instead of about 24

## 26.10.2-beta (2026-10-02)

- Add a health view, opened from the command palette, that checks Ollama, how much of the main model sits on the GPU and how long it took to load, the graphics adapters against the installed CUDA or ROCm PyTorch build, and the voice service device and CosyVoice load time
- Add automatic opening of a Now playing panel to the right of the active panel when a song starts playing, once per song so that closing it is respected, with the song detection running in the background while Morgan is open
- Add Back Up and Restore buttons to Settings, next to Remove Memories, that save the memory database, Nova's reminders and events and the daily logs to one zip file and bring them back from it, migrating older backups to the current schema
- Add Check for Updates button in Settings, above Remove Memories, and a command palette action that look for newer versions in the repository's GitHub releases, let the user choose one, download MorganSetup.exe to the Downloads folder with a progress bar docked at the bottom of the current workspace, install it, delete the installer and start Morgan again
- Add command palette button to the header of every desktop workspace panel, running the same palette as Ctrl+K so it can be opened with a click, with Ctrl+K kept
- Add context length field to Settings, saved in the user configuration instead of dev/core.json and used both for the OLLAMA_CONTEXT_LENGTH set when the services script starts Ollama and for the context Morgan budgets against, so users with less GPU memory can lower it from the default 32768
- Add Copy day and Export buttons to the Nova diary that copy the day as Markdown or save it to a Markdown file, with its agenda, remembered facts and every conversation message
- Add Copy report button to the health view that copies the results with the version, system and check time as Markdown for bug reports
- Add Custom option to the repeat choice of the Nova overlay and form, in the desktop and terminal versions, with an interval from 1 to 999 and an hours, days, weeks, months or years unit
- Add custom repeat intervals to Nova reminders and events, such as every 2 weeks, every 15 days or every 3 hours, accepted by the repeat parameter of the add_reminder, add_event and update_agenda_entry tools together with hourly and yearly, with the Nova databases migrated to the wider schema and repeating events expanded by the hour
- Add daily, weekly and monthly repeats to Nova reminders and events, chosen in the entry overlay or through a repeat parameter on the add_reminder and add_event tools, with repeating reminders moving to their next time when due or completed and repeating events shown on every day they happen
- Add due Nova reminder notifications to the terminal version, shown as Windows toasts with In 10 min, Tomorrow and Done buttons and a notice in the status line, sharing its Nova records with Morgan's tools
- Add edit button to the reminder and event rows of the Nova agenda, reminders, events, diary and search, opening the overlay to change the title, time, notes and repeat
- Add Exit Morgan command in the command palette that stops any running reply and closes Morgan gracefully, so the session end time is recorded without ending the process from the Task Manager
- Add flag choice to the Nova form and colored flags to the entry rows of the terminal version
- Add flag field to Nova reminders and events, stored as none, green for unimportant, yellow for important or red for high priority, like the iOS Reminders app, and set through a flag parameter on the add_reminder, add_event and update_agenda_entry tools, with the agenda brief naming important and high priority entries
- Add flag selector and green, yellow and red flags to the Nova overlay, rows and calendar chips of the desktop version, to mark reminders and events as unimportant, important or high priority
- Add health check on the first start of each new version, run once the services had time to start, that opens the health view with the results when a check fails
- Add In 10 min, Tomorrow and Done buttons to due Nova reminder notifications, now shown as Windows toasts that stay on screen, with a click on the toast opening the Nova agenda
- Add logging of every memory tool call and its result, including failures with their error, to the agent log, with the arguments left out in private mode, so a memory that was not saved can be traced instead of failing silently
- Add notice, in the interface language, under a reply that says a memory was saved, updated, deleted or pinned when no memory tool succeeded in that turn and no other action did either, found by asking the model one yes or no question about the reply, so Morgan no longer leaves the user believing something was stored when it never called the tool
- Add Nova search, a sidebar section with one box that finds reminders, events and the diary days whose conversations mention the words typed, opening the day in the diary when clicked
- Add Nova to the terminal version, opened from the palette, Ctrl+Alt+N or Ctrl+L, with the agenda, reminders, events, a month calendar, the diary with unfoldable conversations and Markdown export, the week review and its summary, memories with pinning and editing, search, and a form to create, edit and delete reminders and events
- Add Nova Week, a weekly review section that shows the reminders done, pending and missed, the events, conversations and new memories of each week, the days with activity opening in the diary, and a Summarize button that asks the main model for a short review of the week
- Add Ollama button, drawn with the Ollama llama, to the left of the context length field in Settings, that stops every Ollama process and starts the server again with the configured OLLAMA_CONTEXT_LENGTH after confirmation, so a new context length applies without the services script
- Add Open the song panel switch to Settings that turns off the automatic opening of the Now playing panel when a song starts, remembered between sessions
- Add pin_memory tool and a pinned option on remember, so Morgan can pin or unpin a memory when asked or store one already pinned for requests like "always remember that ...", with list_memories showing which are pinned
- Add pinned memories that are always placed first in the model's context, and a Nova Memories section to review every stored memory and pin, edit or remove it
- Add choice dialog to the terminal version, with a centered title and message over a grid of buttons that answers to arrows, Tab, Enter, the mouse and Esc, queues questions and now shows the command permission request instead of its own box
- Add choice dialog built into the Settings view, a scrim with a small centered card and gridded buttons, replacing the separate Qt message windows of Remove Memories, Remove Markdowns, Back Up, Restore and the Settings warnings, and reusable by anything that needs a choice
- Add Remove Markdowns button to Settings, next to Remove Memories and in the same red, that deletes every daily log and session artifact after confirmation, keeping the memories, conversations, settings, themes and the Nova agenda
- Add scrolling to the model selector list of the desktop version, showing four models at a time
- Add search_agenda tool that lets Morgan find Nova reminders and events by the words in their title or notes, past or upcoming, when their date is unknown
- Add seek_media to the media controls, moving the playback position of a Windows media session or of Spotify
- Add song detection that finds the song playing on Spotify or in a browser through the Windows media sessions, leaving out videos, podcasts and ads, confirms it as a track and takes its album art through the Spotify Web API when Spotify is already authorized, and follows songs playing on other Spotify devices without ever opening the browser to authorize
- Add song summary written by the main model in the interface language, in at most 500 words, from web search results and one page about the song: what the lyrics are about, their themes and fun facts such as interviews with the singer or band and the history of the album
- Add song view with the album cover, a progress bar that seeks when clicked, previous, play or pause and next buttons wired to the player, Song, Album and Artist buttons that copy each name, and a Summarize button, with its interface text in English, Spanish and Chinese
- Add update checks to the terminal version, from a Check for updates palette action that lists the newer releases, downloads the chosen one with a progress box above the composer, installs it and starts the terminal version again
- Add update_agenda_entry tool that lets Morgan rename, move or reschedule a Nova reminder or event from chat while keeping its ID and repeat, instead of deleting and adding it again
- Fix Morgan apologizing for a failed tool call and asking for a second confirmation when saving a reminder or event, because reading the clock first counted as a first action and moved the second one, the Nova entry, into supervision, which rejected it until a task contract existed
- Fix Morgan ending a task with "Exceeded maximum output retries" when the model's tool call could not be parsed and came back as an empty reply, because the framework gave up after one retry and a read-only task contract demanded a nested verification map that the model could not write, so empty replies now go through Morgan's own recovery, which stops cleanly after three attempts, and read-only criteria no longer need an explicit verification
- Fix Morgan failing to save a memory when the model chose a category outside the allowed list or sent an empty or spaced key or an expiration without a time zone, by listing the allowed categories in the remember tool, turning keys into underscored words, ignoring empty keys and expirations and reading an expiration without a time zone as local time
- Fix Morgan losing the delete, update, list and search agenda tools after saving a reminder or event, because a request too large for the context kept only the tools used in the last messages, so every Nova tool now stays available together
- Fix Morgan not accepting requests to write down reminders, events or tasks in Nova, because its instructions only described notifications and timers, and refresh the saved instructions that were never edited
- Fix Morgan refusing to remember, forget or pin something unless the message began with one of a fixed list of English or Spanish verbs, so wordings such as "Hey Morgan, remember ...", "yes, store it" or "recuérdalo" were rejected, by removing that keyword check and instructing the model to call the memory tool in the same turn, in any wording or language
- Fix Morgan repeating remembered facts in the first person, such as "My mother's name is ...", instead of reading them as the user's own memories and answering "Your mother's name is ..."
- Fix Morgan staying open after being asked to close itself during a reply, because the shutdown waited on a quit request that had already been marked as handled
- Fix model selector list covering the selector when opened upward, by keeping it anchored above the selector with a small gap while it resizes
- Fix model selector list visibly jumping and sliding into place when opened, by keeping it invisible while it is moved above the selector and showing it only once it is in its final position
- Fix dropdown lists of Settings showing smaller text than the chosen option above them, and the model selector list opening with a gap above the selector, by sizing the items like the chosen option and starting the list right at the top of the selector, shrinking the list to scroll when there is not enough room above
- Fix installer finishing without any sign of a failure when the runtime setup did not complete, leaving no Python environment behind, by running the setup inside the installer and showing an error with its exit code and how to resume
- Fix Nova events not opening in the edit overlay, and adding or updating them failing in the desktop version, because Qt's own event method hid the store's event lookup, now called find_event, which also let update_agenda_entry find events again
- Fix services launcher showing only a bare timeout when CosyVoice fails to start, by printing the last lines of the voice log before the error, and explaining that a missing Python environment means the runtime setup must be completed by running the installer again
- Fix Settings being squished when its panel is short, such as at the top or bottom of the screen, by placing it in a scroll area with a hidden scrollbar, with the mouse wheel over a dropdown scrolling the page instead of changing the dropdown
- Fix small blank windows flashing on screen when a Nova list is rebuilt, as when opening the diary with Ctrl+L, because the old rows were detached while still visible
- Fix snoozing a due Nova reminder giving no sign of its new time, by confirming it in a notification or saying the reminder no longer exists, and Tomorrow on a daily reminder adding a duplicate at the time it already repeats
- Fix the Ollama restart button flashing several console windows and leaving two llama-server.exe running, because the server was started detached from any console, so every process it launched opened its own window, and its model runners from before the restart were never stopped
- Fix voice service hanging until the startup timeout when the CosyVoice model folder is missing, because the model loader tried to download the local path as an online model, so it now stops at once with a message naming the missing folder
- Remove the /exit, /private and /reload slash commands in favour of the command palette, which gains Toggle private mode in the desktop and terminal versions and Reload modules in the desktop, while reload and ref still work as messages
- Update command permission, cloud model, update, unsaved changes, attachment and error popups of the desktop version to the choice dialog, shown over the window or editor instead of a separate Qt window, with queued questions, a scrolling list for the releases to install and Esc or a click outside answering as cancel or No
- Update desktop and terminal builds to leave out lingua, babel, num2words and the speech text module, which only the voice service uses and which the voice runtime already installs, so MorganSetup.exe no longer bundles the 290 MB language detector
- Update flag selector of the Nova overlay to a horizontal track with a colored pill for the chosen flag, like the permissions selector
- Update installer to download the 62 MB timezone data from PyPI during runtime setup into the models folder instead of bundling it in the desktop and terminal builds, with get_current_time reading it from there or from the installed package when running from source, and reporting a missing download clearly
- Update installer to ship only the voice service modules and locales in the src folder, stop installing the dev folder and remove both old copies on upgrade
- Update model selector list of the desktop version to open upward, above the selector, when there is room on the screen
- Update Nova agenda tools and instructions to take a date alone, loose date and time formats, a time zone suffix read as local time and null optional arguments, and to write the reminder or event at once with the date and time Morgan is already given instead of calling get_current_time or asking for a second confirmation
- Update Nova diary header to place the copy, export, previous entry and today buttons in a row below the day and the previous and next day arrows
- Update Nova flag and custom repeat choices of the overlay and form to symbols, with one, two or three flags for unimportant, important and high priority and a pencil for Custom, and remove the translated flag names and Custom label
- Update Nova flag symbols in the desktop overlay to have a space between them
- Update Nova lists to show flagged entries first, red then yellow then green, in the agenda days, overdue and pending reminders, upcoming events and the day lists of the diary and the terminal version
- Update Nova sidebar icons and star to be 15% larger
- Update Nova storage, agenda grouping and the diary and week helpers to work without Qt, so the terminal version can read and write Nova and Morgan's Nova tools and agenda greeting work there too
- Update README to list the current features, document updates from Settings and remove the regression check commands for test folders that no longer exist
- Update services launcher to read the bundled core.json when the dev folder is not installed
- Update Settings dropdown lists to have all four corners rounded to 12 pixels
- Update Settings buttons, the themes folder, updates, backup, restore and remove memories, to a three column grid at the bottom that adds rows as buttons are added
- Update startup greeting to briefly mention today's Nova reminders, events and overdue reminders when there are any
- Update startup greeting to open with a plain salutation and the user's name, without Morgan introducing itself each time
- Update workspace panel header buttons, the command palette and close buttons, to be 10% larger
- Update workspaces documentation to name the Nova diary, not the removed conversation logs, as a place whose web links open in the default browser

## 26.10.1-beta (2026-10-01)

- Add ARLO Home, the 26th built-in color theme, in blues and whites
- Add Chinese (Simplified) as an interface language, selectable in Settings and the terminal version, with Chinese dates in Nova and wake word detection
- Add Ctrl+L shortcut and Open diary command that open Nova on the Diary, reusing an open Nova panel
- Add Nova as a workspace view, with a sidebar folded into the panel, agenda, reminder and event lists, and an overlay to create, edit and delete entries, opened with Ctrl+Alt+N or the command palette
- Add Nova calendar widgets with week, month and year views, drill-down between them, a date picker and Spanish and English day and month names
- Add Nova diary remove buttons next to each message copy button and on each conversation, which after a second click delete the message or the whole conversation from the memory database and the daily Markdown log
- Add Nova diary that presents the memory database one day at a time, with the day's agenda, remembered facts and unfoldable conversations
- Add Nova persistence with one SQLite database for reminders and another for events, stored in the Morgan user folder, with due-reminder tracking
- Add Nova star button to new workspaces that slides out the other workspace buttons and opens Nova with Ctrl+click
- Add Nova tools that let Morgan add reminders and events, list the agenda and complete or delete entries from chat, so requested reminders persist across restarts and appear in Nova
- Add Remove Memories button to Settings that deletes every stored conversation, memory, daily log and session artifact after confirmation, keeping settings, themes and the Nova agenda
- Fix Morgan forgetting stored facts such as family names and pets by including every confirmed memory in each turn again, relevant ones first and within the context budget
- Fix command confirmation crashing with an undefined sys module when no confirmation dialog is attached, instead of declining the command
- Fix directory change and module reload commands being stored as conversations, and remove the ones already stored
- Fix due Nova reminders being marked as announced without a notification when they came due more than a day earlier while Morgan was closed, and group more than three due reminders into one notification
- Fix installer failing to replace a CPU PyTorch with the CUDA build on NVIDIA GPUs, because pip treated the pinned version as already installed
- Fix installer setting up CPU PyTorch on AMD Radeon RX 9000 GPUs by installing the ROCm build for them, and reinstalling PyTorch when an existing runtime does not match the GPU
- Fix log pruning that deleted unrelated YYYY-MM-DD.md files because its header check never matched and failed on unreadable files
- Fix memory updates failing with a database constraint error when the new content or key already belonged to another active memory
- Fix Nova diary conversations not unfolding when their header was clicked, because the ignored mouse press kept the release from reaching them inside the zoomable window
- Fix response workspace never opening on its own: final answers with no chosen surface now go to it when they are long, have several code blocks or follow a web search, unless the chat is requested
- Fix saved instructions in config.json never receiving updated defaults, by refreshing the ones that were never edited and keeping edited ones
- Remove the chat button from new workspaces and the Focus Chat palette command, which only focused the main chat
- Remove the embedded browser, its extension manager, persistent sessions, Ctrl+B shortcut and Open browser command, which also drops Qt WebEngine from the app
- Remove the Logs workspace and its button, Ctrl+L shortcut and command, since the Nova diary shows the same daily conversation messages
- Update docs, stylesheet and executable build to drop the browser rules and the Qt WebEngine exceptions
- Update due Nova reminders to be announced as Windows notifications while Morgan runs
- Update Nova diary copy button to sit in the top right corner of each message and briefly show a tick after copying
- Update Nova diary to show every message of a conversation as a log card with Markdown, a copy button for the content only and live updates, including system and interrupted messages, with the daily Markdown log as fallback
- Update startup greetings to be generated by the main Ollama model from the assistant name and its grammatical gender, in the interface language, replacing the fixed greetings
- Update startup to load CosyVoice while the model preloads and to import the agent runtime while the local services start
- Update theme folder seeding to deliver new built-in themes to existing installs without overwriting edited themes or restoring deleted ones
- Update versioning to the current date in YY.M.D form, starting at 26.10.1-beta
- Update web search to stop opening a browser and to deliver answers based on its results to the response workspace
- Update web searches, website requests, YouTube selections, conversation links and the repository link to open in the operating system's default browser

## 1.4.45-beta (2026-10-01)

- Add 14 new color themes (Ayu Mirage, Dracula, Everforest Dark, GitHub Dark, GitHub Light, Gruvbox Dark, Gruvbox Light, Kanagawa, Nord, One Dark, One Light, Rose Pine, Rose Pine Dawn, Synthwave '84, Tokyo Night)
- Add previous message history with Alt + Up/Down to the desktop chat input
- Add previous message history with Alt + Up/Down to the terminal chat input
- Fix Gemma 4 task_finish parse failures that looped without delivering an answer
- Fix response workspace font size
- Update executable build to exclude unused modules and Qt files (numba, pandas, pyarrow, matplotlib, QML, 3D, debug and devtools resources)
- Update installer to share one runtime between Morgan and the terminal version and use stronger compression, shrinking MorganSetup from 1.1 GB to about 440 MB
- Update voice playback to rebuffer after an underrun and raise the audio thread and process priority
- Update voice service to use the MIOpen fast find mode for a quicker first synthesis

## 1.4.44-beta (2026-10-01)

- Update default model and installer to a single gemma4:e4b
- Update docs for the single gemma4:e4b model
- Update model handling to stop creating arlo-* Ollama copies

## 1.4.43-beta (2026-10-01)

- Add cloud label and consent prompt to the model selector
- Add Ollama cloud model support to model resolution and context budget
- Add terminal version build and installer packaging
- Fix clearing the screen before launching the terminal interface
- Fix installer to always include the terminal version
- Fix terminal version crash on voice input by bundling the current C++ runtime

## 1.4.42-beta (2026-09-30)

- Add dark terminal interface that shares the desktop runtime
- Add direct arlo executable through Python (pyarlo launcher)
- Fix desktop entry point to run directly from Python without PYTHONPATH
- Update launcher scripts and README for the terminal version
- Update shared runtime to run without Qt and with an optional voice service

## 1.4.41-beta (2026-09-30)

- Fix installer to save the chosen assistant name and create the .<name> data folder
- Update storage folder to follow the assistant name instead of a fixed .arlo anchor

## 1.4.40-beta (2026-09-30)

- Add standalone voice runtime setup to the installer without requiring the repository
- Fix services launcher lookup to include the installation folder without ARLO_HOME
- Fix services launcher on Windows PowerShell 5.1 and refresh PATH from the registry
- Update missing services launcher message to make ARLO_HOME optional
- Update voice model lookup to fall back to the assistant data directory

## 1.4.39-beta (2026-09-30)

- Add MorganSetup.iss Inno Setup script and rebuild.bat to the repository
- Fix services launcher lookup falling back to the registry when ARLO_HOME is missing from the process environment
- Update arlo.ico to match the current arlo.png

## 1.4.38-beta (2026-09-30)

- Add automatic CosyVoice model download to runtime setup

## 1.4.37-beta (2026-09-30)

- Fix arlo.png to include the orb's inner fill and match the app rendering

## 1.4.36-beta (2026-09-30)

- Add opaque blended color tokens to theme rendering
- Fix seam marks on the privacy and branch indicator borders
- Update arlo.png to match the current orb rendering
- Update README header with centered title and arlo logo
- Update README to document the installer and current launch scripts

## 1.4.35-beta (2026-09-30)

- No notable changes

## 1.4.34-beta (2026-09-30)

- Fix workspace border dragging passing splitter arguments in the wrong order
- Update response workspace to hide its scrollbars

## 1.4.33-beta (2026-09-30)

- Fix concurrent sessions claiming speech only when an answer is ready
- Fix session panel animation stalling at its minimum width
- Update default main model to qwen3.5:9b

## 1.4.32-beta (2026-09-30)

- Fix startup crash when the day's session log does not exist yet
- Update second session to open as its own workspace panel
- Update working directory to be owned by each session

## 1.4.31-beta (2026-09-29)

- Add closing the second session without restarting
- Add concurrent desktop sessions limited to two
- Add session selector widget and session strings
- Update default main model to deepseek-r1:8b
- Update desktop audio lease to be shared across session threads

## 1.4.30-beta (2026-09-29)

- Fix removal of legacy arlo-01 to arlo-08 voices from the selector
- Update microphone icon on the send button to a larger size

## 1.4.29-beta (2026-09-29)

- Update voice reference text to be gender neutral
- Update voices reduced to 4 profiles, covering both genders

## 1.4.28-beta (2026-09-29)

- Add new voice profiles and remove the old ones

## 1.4.27-beta (2026-09-29)

- Fix runtime setup to derive the data directory from the assistant name
- Fix wake launcher resolution from the assistant installation variable

## 1.4.26-beta (2026-09-29)

- Fix composer icon sizing across workspace and theme changes
- Fix microphone icon to be smaller

## 1.4.25-beta (2026-09-29)

- Add built-in Catppuccin, Monokai, Solarized and custom themes
- Add theme discovery, persistence and runtime switching
- Add theme selector and themes folder button to settings

## 1.4.24-beta (2026-09-29)

- Update microphone icon size

## 1.4.23-beta (2026-09-29)

- Add generic theme contract with Catppuccin Macchiato default
- Update painted components to use theme roles
- Update stylesheet to resolve colors from theme roles

## 1.4.22-beta (2026-09-29)

- Add behavior claims to supervised verification criteria
- Fix verify-phase checks leaving unresolvable system obligations

## 1.4.21-beta (2026-09-29)

- Add AUTO permission mode and fail-closed ASK timeout to confirmations
- Add permission mode pill selector
- Add permission mode setting to user config
- Fix permission_mode to store plain JSON strings

## 1.4.20-beta (2026-09-29)

- Fix promoted mutation verification deadlock after direct effects
- Fix self-code path hints and read_code start line zero
- Fix steering resume and completed task interruption
- Fix supervised verification stalls and add task cancellation
- Fix task_checkpoint completed citations leaving effect obligations open
- Fix task_finish ignoring verified evidence for effect obligations

## 1.4.19-beta (2026-09-29)

- Fix promoted tasks losing inspection tool schemas under the context budget
- Fix supervised checkpoints hiding pending evidence requirements

## 1.4.18-beta (2026-09-29)

- Fix inactive tool schemas causing invalid argument loops
- Fix packaged terminal closing by bundling winpty OpenConsole
- Update source tool path guidance for project root and tagged paths

## 1.4.17-beta (2026-09-29)

- Add @ file tagging of the working directory in the chat input
- Fix file tag popup background not rendering
- Fix file tag popup freezing the chat input inside the zoom view
- Update remove install.sh and its README references

## 1.4.16-beta (2026-09-29)

- Add file size metadata to directory listings
- Add model selector to the input indicator row
- Add persistent main Ollama model selection to runtime
- Add setup-runtime script
- Fix command palette clipping and results shown before typing
- Fix interrupted execution recovery and local command association
- Fix privacy and model indicator padding and border radius to match the row
- Fix repeated evidence progress and verification reuse
- Fix resuming suspended tasks by session identity
- Fix tool schema selection during supervised promotion

## 1.4.15-beta (2026-09-28)

- Add composite tool execution metadata
- Add declarative tool followup policies
- Add lazy execution supervision and prior observation import
- Fix discovering tools from the registry under context limits
- Fix installer assistant name validation
- Fix isolating new requests and resuming tasks explicitly
- Fix launcher lookup for custom assistant names
- Update agent routing and session-aware task resumption
- Update installer for Inno Setup integration
- Update the main header.png

## 1.4.14-beta (2026-09-28)

- Add dynamic PyInstaller build with Windows icon
- Fix ARLO_HOME definition
- Fix background terminal popups in PyInstaller builds and the packaged app
- Fix confirmed flowchart evidence in task supervision
- Fix conversational recovery after failed voice turns
- Fix executable output and launcher paths
- Fix finalized voice transcripts and response routing
- Fix flowchart availability under context budgets
- Fix frozen desktop startup and executable launch
- Fix Git diff panel rendering and initialization
- Fix Git diff workspace loading and refresh
- Fix Git status parsing and translate the connector to English
- Fix immediate streaming and certified response delivery
- Fix immediate working directory commands
- Fix live audio transport and meter overhead
- Fix local service startup before runtime initialization
- Fix localization for steps in task progress
- Fix loopback delays and redundant voice filtering
- Fix missing speech detection assets in packaged app
- Fix native audio model context provisioning
- Fix packaged microphone startup with SciPy source loading
- Fix recent conversation retention during context compaction
- Fix task progress overlay close button
- Fix tool schema selection before session compaction
- Fix transient voice connection refusals during startup
- Fix verified task completion and finalization loops
- Fix voice fallback to transcribe before answering
- Fix wake script to execute the executable on Windows
- Fix WAV context estimates using audio duration
- Update context budgeting and compaction infrastructure
- Update installer with FFmpeg and executable environment
- Update main launcher to arlo-start.bat and remove arlo.bat
- Update persistent voice loading and idle memory reclamation
- Update response delivery infrastructure
- Update simplified Git diff workspace

## 1.4.13-beta (2026-09-27)

- Add configurable assistant identity across prompts and UI
- Add context-aware numeric speech normalization
- Add continuous voice conversation with speech interruption and echo suppression
- Add current evidence IDs to completion requirements
- Add deterministic activity trail and shared task presentation
- Add Git diff workspace for Git differentials
- Add palette commands to stop, pause and resume tasks
- Add protected migration for named storage and service namespaces
- Add read-only workspace file viewers (including PDF)
- Add setting to toggle ephemeral activity steps
- Add terminal command execution in the palette
- Add unified desktop file drop routing
- Add workspace-local command palette
- Fix accepting matching source cursor arguments
- Fix audit contract declarations and repeated inspection repairs
- Fix command palette label alignment during startup
- Fix commit scope to preserve concurrent core changes
- Fix condition speech on a stable response language
- Fix context_tokens length, task handling and state machinery
- Fix CosyVoice phrase startup and ready audio delays
- Fix direct conversation completion without task contracts
- Fix false continuation after evidence delivery completes
- Fix fictional barrier on long complex tasks
- Fix font rendering as global and task_control pending finalization
- Fix installer directory and Windows import paths
- Fix keeping the orb stationary when task progress appears
- Fix map task lifecycle to session message status
- Fix missing localizations for warnings
- Fix missing task dependencies and mutation tool selection
- Fix negative source listings and search limit schema
- Fix Ollama reasoning disable parameter
- Fix orb thinking animation during response preparation
- Fix output recovery through actionable control turns
- Fix palette input and sizing in zoomed workspaces
- Fix partial task criteria updates and translate the stall warning
- Fix portable Windows installation dependencies
- Fix preserving source evidence within the context budget
- Fix preserving task context and stopping inspection loops
- Fix preserving the first complete speech sentence
- Fix preserving the voice reference when controlling speech language
- Fix preventive context budgets and recoverable tool evidence
- Fix readonly voice model assignment during installation
- Fix repeated output recovery without task progress
- Fix response timing
- Fix shared verification contracts for mutation criteria
- Fix source read range contract and validation errors
- Fix stream speech prose before line completion
- Fix supervisor state recovery and progress accounting
- Fix verified final answers without extra completion turns
- Fix voice number language and bypass English normalization
- Update answer routing to share the main model turn
- Update command palette placement above the orb
- Update command palette to show results only after typing
- Update configured assistant names in messages and translations
- Update generic assistant identifiers and storage bootstrap
- Update native voice input and shorter speech phrases
- Update source page capacity and empty search guidance
- Update wake recognition and voice services to use the assistant identity

## 1.4.12-beta (2026-09-27)

- Add SPECS.md with the project specifications
- Fix chat input scrollbars to remain hidden
- Fix deterministic single-agent task supervision
- Fix objective task titles and stable title delivery
- Fix recoverable task completion and incremental execution journals
- Fix response timer display formatting
- Fix send button alignment with the input row
- Fix source inspection pagination with revision-bound cursors
- Fix thinking ring with continuous angular progress animation
- Fix workspace composition and progress geometry

## 1.4.10-beta (2026-09-26)

- Add substantial use tracking of tools and blocks without parameters

## Pre-1.4.10

- Add ACTION-EXECUTION.md documentation
- Add agent LLM mode with full TaskControl integration
- Add allowlisted Windows queries and PowerShell tools
- Add application icon and a custom personal icon for Morgan
- Add application name normalization and ranking for open_application
- Add application opening and window listing methods
- Add app_cache to cache applications for faster lookups
- Add Morgan as a background process, detached from the launcher terminal
- Add Morgan mascot and ring in the new desktop package
- Add Morgan microphone recording and speaking
- Add Morgan response latency timer pill
- Add Morgan's wake word script (wake.py)
- Add assistant command execution in terminal workspaces
- Add attachments system with attachment cards and a per-file size limit
- Add ATTACHMENTS.md documentation
- Add audio meter animation
- Add audio visualizer module
- Add autonomous agent execution core
- Add bounded read-only project inspection models
- Add bounded source inspection telemetry
- Add built-in terminal integration in workspaces
- Add bundled fonts (Ubuntu Nerd Font, Inter, JetBrains Mono, Arimo)
- Add change directory and Git directory checking
- Add clickable "Made with Morgan" privacy indicator
- Add clipboard support
- Add color-coded input and output
- Add command execution with confirmation to the desktop interface
- Add commands execution ability through sudo.exe, wired into tools
- Add compact mascot subtitle bubble wired to speech state
- Add config.json and config.py for editable assistant settings
- Add console_input for page scrolling and moving
- Add contextual browsing in workspace panels
- Add copy button for log messages
- Add core.json for the version and model name, separated from config.json
- Add CosyVoice integration to the voice service
- Add current directory widget
- Add debug console in a separate window
- Add desktop visual interface of the Morgan app
- Add DIAGNOSTICS.md documentation for system health checks
- Add drag and drop for the Morgan widget
- Add drop previews while dragging workspaces
- Add editor integration driven by the assistant (pyvim, later neovim)
- Add email drafting tool
- Add email_service for reading, writing and deleting emails
- Add file and directory tools (create, write, edit, delete) with path resolution and text decoding
- Add filters for SQL select queries in memory retrieval
- Add flowcharts with live interactive drawing through the flowcharts API
- Add folder searching and cache
- Add folders module and update how applications and folders are opened
- Add Forge agent mode with planning, persistent approvals, project inspection and conversational memory
- Add Forge and Git branch pills to the indicator row
- Add frameless window
- Add generated assistant banner with pyfiglet
- Add Git features to the assistant
- Add global translator and tool
- Add GNU GPL v3 license
- Add greeting that is random, localized and uses the dynamic username
- Add hot_reload to avoid rebooting Morgan
- Add independent TTS server, voice client and arlo-services script
- Add initial assistant script with Assistant class, chat abstraction and streaming responses
- Add initial README with project description
- Add install and uninstall of applications through app_manager
- Add install.sh script
- Add kill_process, shutdown_computer and cancel_shutdown tools
- Add language and model dropdowns to settings
- Add language strings translations and copyright notices
- Add lexical search through FTS5 indexes for word retrieval in memory
- Add live editor to the desktop interface with syntax highlighting and keyboard navigation
- Add log tab
- Add main workspace open and close animations
- Add messaging with recipient resolution and sending through the WhatsApp Cloud API
- Add multistate orbs with animations and color switching
- Add music session listening methods ("shazam")
- Add mute button
- Add native audio model (Gemma) processing for faster response times
- Add new Morgan voice models and voice profiles with a selection dropdown
- Add new voice models Brian and Gabriel
- Add notifications system with timers
- Add number pronunciation tool for the local language
- Add open current session log
- Add Open-Meteo forecasts and saved weather location
- Add output module
- Add paths module for ARLO_ROOT
- Add per-turn inspection context budget
- Add persisted local session logs
- Add persistent Chromium extension manager to the embedded browser
- Add persistent embedded browser sessions across panels and restarts
- Add persistent memory documentation
- Add Piper voice service for spoken responses
- Add pop-in and pop-out animations for the orb
- Add private mode to keep conversations from being logged
- Add project inventory boundaries for Forge
- Add pronunciation persistence
- Add proper app closing in combination with commands
- Add quick command groups executed through registered tools
- Add reader.py for image reading with a dedicated Ollama vision model, plus image and screen analysis tools
- Add refresh method to reload the assistant
- Add repository link tool
- Add requests redirected to the built-in browser instead of the native one
- Add requirements.txt
- Add resource_path function for packaged installer
- Add response workspace bridge with highlighting
- Add Rich terminal
- Add rules script to hold all instructions given to the agent
- Add screenshotting function for Morgan
- Add script to set up Morgan at boot (optional)
- Add search_code tool to search codebase structures
- Add self_code to let the assistant read and change its own code live
- Add session context and artifact storage
- Add settings button and settings page
- Add smart browser integration
- Add spinner animation
- Add Spotify integration with OAuth and Spotify Dev API playback
- Add SQLite persistent memory system
- Add Steam games manager
- Add streamed workspace response panels
- Add streaming for both terminal and UI interfaces
- Add subtitle background with dynamic sizing
- Add subtitles parsing and subtitles toggle switch
- Add symbol indexes to source inspection
- Add system health diagnostics (telemetry, scanner and scoring)
- Add tabs to the interface
- Add task progress widget
- Add tool for Morgan to close itself
- Add tools.py to break down the main agent
- Add version number for the assistant
- Add voice commands
- Add voice IPC and wake capturing
- Add wake word documentation (WAKE-VOICE.md)
- Add web searching with verified sources check
- Add Windows playback controls and YouTube song selection
- Add word-level subtitle timeline synced with spoken words
- Add workspaces system with animations, shortcuts, dragging and renaming
- Add WORKSPACES.md documentation
- Add zoom and scaling to the interface
- Fix agent plan grounding and execution evidence
- Fix app opening and lookup methods
- Fix application launching, window verification and premature success responses
- Fix Morgan closing after a shutdown request
- Fix Morgan hanging after any request
- Fix Morgan hearing and replying to his own speech
- Fix Morgan looping on the same actions over and over
- Fix Morgan speaking delay and pauses between sentences
- Fix assistant announcing an action and never executing it
- Fix barge-in mechanic and wake word interruptions
- Fix cache emptying in model.py
- Fix chat input expansion on scrolling
- Fix compatibility between CPU and GPU setups by making the voice script CUDA-agnostic
- Fix CosyVoice empty final inference
- Fix emails that could not be loaded
- Fix File Explorer application launch
- Fix flowchart workspace target resolution
- Fix folders.json not being read correctly
- Fix Forge approval routing and continuity
- Fix Forge plan validation, replanning and read-only enforcement
- Fix frozen timer on Morgan's actions
- Fix ghost launching of Morgan
- Fix hot reload of modules
- Fix logs not rendering in the log tab
- Fix long-term memory isolation from active tasks
- Fix memory leak on temp tables
- Fix native Gemma action reasoning and voice context
- Fix normal chat session history retention
- Fix persistent conversation continuity
- Fix privacy indicator button not working
- Fix Qwen structured tool context
- Fix response timer never stopping
- Fix retrieval of personal memories
- Fix speaking_enabled to avoid the "vertical bar" bug
- Fix speech patterns with tables
- Fix Steam games detection and launching
- Fix subtitles cutoff and not clearing after Morgan finishes
- Fix task progress and compact workspace layout
- Fix task_control recovery, loop breaking and execution safeguards
- Fix tool continuation and response streaming
- Fix truncated model response continuation
- Fix wake words, recording sessions and how Morgan reacts
- Fix web search suddenly not working
- Fix workspace panel dragging and splitter resizing
- Remove built-in editor tabs
- Remove Forge runtime integration and UI
- Remove neovim from dependencies
- Remove power request shortcuts and support graceful Morgan closure
- Remove terminal and agent integration, reworking Morgan into a desktop interface only
- Remove usage limits
- Update agent instructions to be more explicit and safeguarded for the LLM
- Update agent runtime to use a shared Assistant class with a singleton identity
- Update agent.py into smaller modules (brain, rules, tools, voice, spin)
- Update Morgan as an independent Windows app
- Update Morgan setting for pulsating the orb whilst speaking
- Update Morgan's orb design to 2 rings
- Update Morgan's private indicator
- Update Morgan's thinking state animation
- Update Assistant class into core.py and reduce agent.py features
- Update basic config.json into a more robust editable version
- Update code blocks to remain in conversation logs
- Update default model to deepseek-r1:8b
- Update desktop.py into modular components (core_ui, orb, worker, chat, indicators, subtitles)
- Update disabled reasoning by default
- Update documentation and legal licenses
- Update documentation naming convention and repository structure (entry, scripts and docs folders)
- Update embedded browser performance
- Update flowcharts to be part of the workspace system
- Update log view with new styling and timestamp format support
- Update main script into a more robust version
- Update memory instructions policy and memory retrieval tools
- Update Nora personality to be less childish, less serviceable and adjustable live
- Update Nora to Morgan
- Update Ollama redirection towards GPU instead of CPU
- Update Orb as the focus of Morgan's identity and unify the Orb
- Update Orb with circular audio spectrum
- Update pronunciation of paths and technical terms
- Update response workspace design and table formatting
- Update scripts into a unified arlo-run.ps1 launcher and arloui and arlo-tui launchers
- Update session logs to match the terminal 1:1
- Update shortcuts for creating and switching between workspaces
- Update speech speed so Morgan replies faster
- Update speech to skip symbols such as * and -
- Update speech to stream before synthesis completes and start the first spoken phrase sooner
- Update starting over with the pydantic-ai framework
- Update startup to speak the greeting with animated orbs and the status above subtitles
- Update stylesheet to its own file (arlo.qss), separated from desktop.py
- Update subtitles synchronization with speech playback
- Update system actions and spoken power requests to route through confirmed tools
- Update task progress window to live inside the main workspace
- Update terminal layout, colors and styling with Rich
- Update to a safer .venv virtual environment
- Update workspace animations to expand horizontally from center
- Update workspaces so response and flowchart panels open on the right
