# Data Studio MCP server

A per-conversation analysis workspace for agents. It provides the same kinds of tools Claude uses for data work:
stateful Python, SQL, document reading, OCR, and generators for decks, dashboards and reports.

| Tool | What it does |
|---|---|
| `ingest_file` | Saves an attachment (base64) in the workspace. The agent runtime calls it automatically for every attachment and hides it from the LLM |
| `list_files`, `get_file_link`, `delete_file` | Workspace management with signed download links |
| `inspect_file` | Profiles any file: every sheet of CSV/XLSX/Parquet/JSON (types, nulls, stats, sample), PDF text and tables per page, DOCX, PPTX, images. `ocr=true` runs Tesseract (por+eng) on images and scanned PDFs |
| `list_tables`, `run_sql` | DuckDB over every tabular file (one view per file/sheet). `save_as` writes the full result as .xlsx/.csv/.parquet/.json |
| `run_python` | Stateful Jupyter kernel with pandas, numpy, duckdb, scipy, scikit-learn, statsmodels, matplotlib, seaborn, plotly, openpyxl, python-pptx, python-docx, pdfplumber, Pillow, pytesseract. `plt.show()` figures become PNGs |
| `create_presentation` | 16:9 **PPTX with native, editable charts**, tables, KPI cards, images and speaker notes, plus a self-contained **HTML deck** (keyboard navigation, fullscreen). Chart, table and KPI data can come from SQL on the workspace |
| `create_dashboard` | Interactive **HTML dashboard**: KPIs, Plotly charts (bar/column/stacked/line/area/pie/doughnut/scatter/heatmap), searchable and sortable tables, insights |
| `preview_file` | Renders a PPTX/DOCX/XLSX/PDF with LibreOffice into one PNG per slide/page and **returns the images to the agent** (vision), so it can check its own deliverable: cut text, empty charts, overflowing tables. Flags blank pages |
| `create_document` | Markdown report to **DOCX** / HTML / MD, with `[[table: SELECT …]]` and `[[image: figura_1.png]]` blocks |
| `fetch_url` | Public web pages as readable text, or data files saved into the workspace. Private and internal addresses are blocked |
| `reset_python` | Restarts the conversation's kernel |

HTML deliverables load Chart.js/Plotly from jsDelivr by default. Pass `offline=true` (or set `OFFLINE_HTML=1`) to
embed the library, so the file opens without internet. The copies are downloaded at image build time, pinned to the
same versions. KPI formats include `brl_compact` / `usd_compact` / `compact` ("R$ 6,26 mi").

## Sessions and isolation

The session comes from the `X-Session-Id` header, which the Agent Hangar runtime forwards from the client's
conversation id. Each session gets:

- **its own directory** (`/data/sessions/<sha256(session)[:20]>`, mode 700);
- **its own uid**: the kernel runs through `setpriv` as that uid.

Every tool that reads user files or runs SQL executes **inside that session's kernel**, never in the server process.
Code in conversation A therefore can't read conversation B's files or the link-signing secret. The smoke test
(`tests/smoke_mcp.py`) checks this.

### Sandbox modes (`SANDBOX`, compose `DATA_STUDIO_SANDBOX`)

| | `process` (default) | `container` (recommended for multi-user) |
|---|---|---|
| Where the kernel runs | A process in the Data Studio container, with the session's uid | **One Docker container per session**, from the same image |
| Files it can see | Its own workspace dir (mode 700) | Only its own workspace, mounted via a volume **subpath** (Docker Engine 26+) |
| Limits | Shared by all sessions | Per session: `SANDBOX_MEM` (2g), `SANDBOX_CPUS` (1), `SANDBOX_PIDS` (256), read-only root FS, `cap_drop: ALL`, `no-new-privileges` |
| Network | Agents network | Its own network `hangar_sandbox` (internet egress, no agents, no database) |
| Needs | Nothing extra | `data-studio-docker`, a socket proxy limited to containers, reachable only by Data Studio |

Idle kernels, and their containers, stop after `KERNEL_IDLE_MIN`. Leftover sandboxes are removed on startup.

### Retention

Workspaces unused for `RETENTION_DAYS` (default 30; `0` keeps them forever) are deleted by an hourly sweep, together
with their kernel. "Use" means any tool call in that conversation.

Limits:
- In both modes, kernels have outbound internet access. An egress allowlist is on the roadmap.
- In `process` mode, CPU and memory are shared (`DATA_STUDIO_MEM` for the whole container), and kernels share the
  agents network.
- In `container` mode, Data Studio can create containers through its socket proxy. As with the hangar itself, a
  compromised Data Studio process is equivalent to Docker access on that host. See `docs/security.md`.

## Ports and configuration

| | |
|---|---|
| `8000` | MCP (Streamable HTTP, stateless). **Internal only**: agents reach it at `http://data-studio:8000/mcp` |
| `8001` | Signed downloads `/f/<session>/<token>/<file>`, published as `127.0.0.1:${DATA_STUDIO_PORT:-8095}` |
| `PUBLIC_URL` | Base URL used in links (`DATA_STUDIO_PUBLIC_URL`, default `http://localhost:8095`) |
| `MAX_FILE_MB` | Maximum attachment size (200) |
| `KERNEL_IDLE_MIN` / `MAX_KERNELS` | Idle kernel shutdown (45 min) and concurrent kernels (24) |
| `RETENTION_DAYS` | Delete workspaces unused for N days (30; 0 = never) |
| `OFFLINE_HTML=1` | Embed chart libraries in HTML deliverables by default |
| `SANDBOX` | `process` or `container` (see above) |
| `ALLOW_PRIVATE_FETCH=1` | Lets `fetch_url` reach private addresses (off by default) |

## Run and test

```bash
docker compose --profile data-studio up -d --build data-studio
docker run --rm --network hangar_agents -v "$PWD/mcp-servers/data-studio/tests:/t" \
  agent-hangar/mcp-data-studio python /t/smoke_mcp.py
```

Register it in the catalog as `data-studio` → `http://data-studio:8000/mcp` (the `data-studio` template does this).
