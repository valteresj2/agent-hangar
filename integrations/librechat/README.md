# LibreChat powered by Agent Hangar

This kit runs a LibreChat instance whose "model" is an Agent Hangar agent. The default is **Data Studio**: users attach
spreadsheets, CSVs, PDFs or images and ask for analyses, edited data, dashboards or presentations. The files come back
as download links, and charts render inline.

```
LibreChat ──(OpenAI-compatible, invoke key, X-Conversation-Id)──▶ Agent Hangar gateway /gw/data-studio
                                                                        │
                                                            agent container (LLM loop)
                                                                        │ MCP + X-Session-Id
                                                                        ▼
                                                      Data Studio MCP: per-conversation workspace,
                                                      Python kernel, DuckDB, PPTX/HTML/DOCX builders
                                                                        │
                                          download links (http://localhost:8095/f/…) ◀── browser
```

## Why a custom endpoint, and not LibreChat's own Agents + MCP?

| | **Custom endpoint (this kit)** | LibreChat Agents + MCP tool |
|---|---|---|
| Who drives the conversation | The hangar agent: tested, versioned, with its own instructions, skills and tools | A LibreChat agent (a second LLM loop) that calls the hangar agent as one tool |
| Attachments | Sent as real files (base64) and saved in the workspace automatically | The LibreChat agent has to relay content to the tool itself |
| Governance | Versions, stage → prod gate, usage and cost per channel in the hangar | Split across two systems |
| When to use | LibreChat as the front end for your agents | You already build agents in LibreChat and want the hangar agent as one more tool (see the commented `mcpServers` block in `librechat.yaml`) |

## How it works

1. **Endpoint.** `librechat.yaml` declares the custom endpoint `Agent Hangar` with `baseURL: <hangar>/gw/data-studio/v1`.
   It authenticates with an **invoke** key that can only call that agent.
2. **Conversation = session.** The header `X-Conversation-Id: {{LIBRECHAT_BODY_CONVERSATIONID}}` goes through the
   gateway to the agent. The agent forwards it to its MCP servers as `X-Session-Id`, so each LibreChat conversation
   gets its own workspace and Python kernel, and conversations can't see each other's files.
3. **Attachments.** With `fileConfig.endpoints["Agent Hangar"].supportedMimeTypes`, LibreChat sends attachments in the
   OpenAI format:
   - images as `image_url` (base64);
   - PDFs, spreadsheets and other files as `{type:"file", file:{filename, file_data}}`.

   The agent runtime saves every attachment in the workspace through the MCP tool `ingest_file`, and replaces it in the
   prompt with a language-neutral note: `[📎 vendas.xlsx (…) → workspace: vendas.xlsx]`. Images still reach the
   LLM for vision. `resendFiles` re-sends attachments on later turns, and the workspace deduplicates them by content.
4. **Output.** Answers are markdown with links to the generated files (xlsx, pptx, html, docx, png). Currency values
   such as `R$ 10` are escaped for LibreChat's LaTeX renderer (see `LATEX_DOLLAR_CHANNELS`), so they don't turn into
   formulas.
5. **Live progress.** While the agent calls tools, each call streams as `reasoning_content`, e.g.
   `🔧 run_sql: SELECT regiao, sum(receita)… ✓ 0.1s`. LibreChat shows it in a collapsible "Thoughts" block, apart from
   the answer. Quiet periods send SSE keepalives, so neither LibreChat nor a proxy drops the connection. Disable per
   request with `X-Progress: off`, or globally with `PROGRESS_STREAM=off`.
6. **Cheap titles.** `titleEndpoint: "Hangar Titulos"` routes title generation to a second, hidden endpoint with
   `X-Hangar-Mode: lite`: one short LLM call with no tools and no agent prompt. In the test it used about 250 tokens
   instead of about 5,500. `modelSpecs.enforce` hides that endpoint from the model picker.

## Run it

```bash
# 1. Agent Hangar with the Data Studio MCP server
docker compose --profile data-studio up -d --build

# 2. The agent (via the platform MCP, like Claude/Codex would), plus an invoke key saved in examples/data-studio/.invoke_key
HANGAR_TOKEN=<admin key> LLM_CONNECTION=<openai-protocol connection> python examples/data-studio/build_agent.py
#    …or: hangar templates apply data-studio --connection <conn> && hangar ship data-studio
#         hangar keys create librechat --scope invoke --agent data-studio

# 3. LibreChat on http://localhost:3090
cd integrations/librechat && ./setup.sh && docker compose up -d
docker exec -it hangar-librechat-librechat-1 npm run create-user -- you@example.com "You" you <password>
```

Pick a vision-capable model for the connection (images are sent to the LLM). The agent was tested with
`deepseek/deepseek-v4.1-flash` via OpenRouter.

## Things to try

- Attach `examples/data-studio/samples/vendas_2026.xlsx`, `relatorio_fornecedores.pdf` and `quadro_estoque.png`, then
  ask: *"Faça uma análise profunda das vendas, cruze com fornecedores e estoque e traga os 5 principais achados."*
  You get a dashboard, a PPTX, an HTML deck and a cleaned spreadsheet.
- *"Remova as vendas com 10% de desconto, crie a coluna margem e me devolva a planilha."* returns an edited .xlsx that
  keeps the other sheets.
- *"Monte 5 slides com tema escuro recomendando quais fornecedores manter, renegociar ou substituir."*

## Notes and limits

- File links (`DATA_STUDIO_PUBLIC_URL`, default `http://localhost:8095`) must be reachable from the users' browsers.
  In production, put that port behind your reverse proxy with TLS.
- The HTML deliverables load Chart.js/Plotly from jsDelivr. They need internet access to render charts.
- See `mcp-servers/data-studio/README.md` for the Data Studio security model (per-conversation uid isolation) and its
  limits.
