# Local PC health diagnostics

`SystemHealthScanner` returns Pydantic `HealthReport` objects. It does not import
the agent, access its configuration, write reports, or execute repairs. The
existing agent registry exposes three synchronous tools:

| Tool | Default | Scope |
| --- | --- | --- |
| `check_system_health(mode="quick")` | quick | Everyday PC health and resource use |
| `check_system_health(mode="full")` | explicit full request | Extended Windows and hardware observations |
| `check_disk_health(mode="full")` | full | Volumes, physical disks and reliability only |
| `check_security_health()` | quick | Defender and registered antivirus only |

## Data and bounds

- CPU: 3 × 0.4 s samples for quick, 5 × 0.5 s for full; mean, per-logical-CPU
  loads, physical/logical core counts, available frequency. High CPU requires
  every sample to be at least 90%; this is only evidence about this short window.
- RAM: total/used/available GiB, percentage during the same sampling window,
  swap/pagefile where supported. GiB = bytes / 1024³, MiB = bytes / 1024².
- Processes: total and inspected counts, top five CPU and RAM consumers. CPU
  is normalized to total logical CPU capacity (0–100), rather than per-core
  percentages that can exceed 100. Process disappearance/access denial is counted.
- Volumes: drive identifier, filesystem, capacity and free/used space. Remote
  and optical volumes are skipped. Files and directory contents are not inspected.
- Full storage: physical disk IDs, Windows health/operational status and
  available temperature, wear, power-on hours and read/write error counters.
  Missing reliability/SMART metrics are null/unavailable, never hardware failures.
  Lifetime error counts and temperature alone have no universal failure threshold.
- Defender: available protection flags, signature timestamp, quick/full scan
  ages and running mode. Registered antivirus display names provide context;
  registration alone cannot establish that another antivirus is protecting the PC.
  Passive/EDR or third-party configurations remain unverified, without a penalty
  merely for inactive Defender. No antivirus scan is started.
- Windows: version, hostname, architecture and boot time/uptime. System and
  Application events are restricted to the last 24 hours and Critical/Error.
  Quick examines at most 100 per log; full at most 500. One additional event
  detects truncation. Up to 20 groups by provider, event ID, log and level are
  returned, alongside total examined counts and omitted-group/truncation flags.
  No event messages, properties or raw event dumps are returned. Counts are lower
  bounds when the result is truncated or one log is unavailable.
- Full Windows: at most 30 device classes/error codes, fixed EventLog/BFE/
  WinDefend/wuauserv service status, and local Windows Update history. Update
  history examines the latest 20 operations, counts failures within 30 days,
  and reads two reboot-required registry indicators. It does not search online
  for updates or establish whether Windows is fully patched. The last successful
  install is limited to those 20 entries; older failures may already be resolved.

Resource sampling finishes before PowerShell starts, to avoid measuring the
diagnostic queries' startup load as the user's CPU/RAM pressure. Independent
queries run in a pool of four workers. PowerShell is started with
`-NoProfile -NonInteractive -WindowStyle Hidden`, a fixed encoded script,
stdout/stderr capture, and an 8 s quick / 15 s full timeout per query. No shell
command string or user-provided path/command is accepted. Quick normally takes
a few seconds; full may take roughly 45–50 s if multiple providers time out.
These are per-query bounds, not a hard deadline for psutil/Windows driver calls.
Importing on another OS is safe; Windows checks report `unsupported`.

## Score v1 and coverage

Rules live in `scoring.py`; the LLM never calculates the score. Start at 100
for the observed components, subtract 10 per warning / 25 per critical issue,
then cap all penalties from each category:

| Category | Maximum deduction | Rules |
| --- | ---: | --- |
| CPU | 10 | At least three samples, all >=90% |
| Memory | 15 | All >=90% warning, all >=97% critical |
| Storage | 40 | Volume >=90% warning, >=97% critical; Windows abnormal physical status |
| Security | 25 | Defender/real-time flag disabled; active Defender signatures >7 days old |
| Windows | 30 | Critical events; >=20 errors; device errors other than intentional disable; disabled EventLog/BFE; unsuccessful recent updates |
| Processes | 0 | Evidence for resource use; no duplicate load penalty or malware accusation |

Any critical issue or score below 40 makes overall status `critical`. Otherwise
any warning or score below 90 makes it `warning`. A fully assessed scope without
issues is `healthy`; a clean result missing core observations is `unknown`.
No observed components means `score=null`. An incomplete report may have 100
points, but it is never presented as proof that the entire PC is healthy.
`assessed_components`, `incomplete`, per-component `errors`, `unavailable` and
null fields disclose coverage. Optional missing metrics do not reduce the score.
A targeted storage/security score applies only to that scope. Scan age, missing
SMART, a single CPU spike and stopped demand-start services never deduct points.

## Permissions, privacy and errors

The scanner never requests elevation. Most psutil, basic inventory and event
reads can work as a normal user. Storage reliability, some CIM providers,
Defender and event logs may require administrator access or be restricted by
local policy/hardware. Such failures produce structured source/error codes and
leave other checks intact. Elevation is not a guarantee that SMART is exposed.

Only necessary telemetry is returned: no process command lines, executable
paths, usernames, disk serial numbers, document content, credentials, browser
history or event messages. Hostname and process/antivirus names are intentional
inventory fields. Telemetry is passed only to the existing local Ollama agent;
this package makes no network requests. The assistant's natural-language answer
uses the existing conversation-log/privacy behavior.

There is no central technical logger in the project. This package uses Python
`logging` with `NullHandler`; applications may attach a handler explicitly.
Debug records include the source, exception class or exit status, without raw
stdout/stderr, exception messages, personal paths or stack traces. No diagnostic
log file is created. Normal failures are returned as data instead of printed.

## Validation

No installed linter/type-checker configuration exists in this repository.

API references: [psutil sampling](https://psutil.readthedocs.io/stable/),
[storage counters](https://learn.microsoft.com/en-us/powershell/module/storage/get-storagereliabilitycounter),
[filtered events](https://learn.microsoft.com/en-us/powershell/scripting/samples/creating-get-winevent-queries-with-filterhashtable),
[local update history](https://learn.microsoft.com/en-us/windows/win32/wua_sdk/iupdatesearcher-methods).
