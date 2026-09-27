"""Data Studio — MCP server de análise de dados e produção de entregáveis para agentes do Agent Hangar.

Ferramentas no espírito das que o Claude usa para esse trabalho: execução de Python com estado, SQL (DuckDB),
leitura de PDF/Excel/Word/PowerPoint/imagens (OCR), busca de URLs e geração de PPTX, slides HTML, dashboards
HTML e relatórios DOCX/HTML. Cada conversa (header X-Session-Id) tem um workspace e um kernel próprios.

Duas portas: 8000 = MCP (só na rede interna dos agentes); 8001 = downloads assinados (publicada para o navegador).
"""
import asyncio
import base64
import ipaddress
import json
import logging
import mimetypes
import os
import socket
from urllib.parse import unquote, urlparse

import httpx
import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from . import kernels
from . import workspace as ws

log = logging.getLogger("data-studio")
ALLOW_PRIVATE_FETCH = os.environ.get("ALLOW_PRIVATE_FETCH", "") == "1"

INSTRUCTIONS = """Data Studio: workspace de arquivos + Python (pandas, numpy, duckdb, scipy, scikit-learn, statsmodels,
matplotlib, seaborn, plotly, python-pptx, openpyxl, pdfplumber) + geradores de PPTX, slides HTML, dashboards HTML e
relatórios. Anexos do usuário já chegam salvos no workspace (ingest_file). Fluxo típico: list_files -> inspect_file
-> run_sql / run_python -> create_dashboard / create_presentation / create_document -> devolva os links."""

mcp = FastMCP("data-studio", instructions=INSTRUCTIONS, stateless_http=True, json_response=True,
              streamable_http_path="/mcp",
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


# ------------------------------------------------------------------ utilidades
def sid_of(ctx: Context) -> str:
    req = getattr(ctx.request_context, "request", None)
    raw = req.headers.get("x-session-id") if req is not None else None
    sid = ws.session_id(raw)
    ws.touch(sid)
    return sid


def sweep_expired() -> list[str]:
    """Apaga workspaces sem uso há mais de RETENTION_DAYS (e derruba o kernel da sessão, se houver)."""
    gone = ws.expired()
    for sid in gone:
        kernels.reset(sid)
        ws.purge(sid)
    if gone:
        log.info("retenção: %d workspace(s) apagado(s)", len(gone))
    return gone


async def _retention_loop():
    while True:
        await asyncio.to_thread(sweep_expired)
        await asyncio.sleep(3600)


async def kcall(sid: str, fn: str, timeout: float = 180, **kwargs):
    """Executa app.kernel_api.<fn>(**kwargs) DENTRO do kernel da sessão (uid da sessão) e devolve o retorno."""
    payload = base64.b64encode(json.dumps(kwargs, default=str).encode()).decode()
    code = ("import json as _j, base64 as _b\nfrom app import kernel_api as _ka\n"
            f"_r = _ka.{fn}(**_j.loads(_b.b64decode('{payload}')))\n"
            "print('\\x1eRESULT' + _j.dumps(_r, ensure_ascii=False, default=str))")
    k = await asyncio.to_thread(kernels.get, sid)
    r = await asyncio.to_thread(k.execute, code, timeout)
    if r.get("error"):
        raise ToolError(r["error"].strip().splitlines()[-1] if r["error"].strip() else "erro")
    out = r.get("stdout", "")
    if "\x1eRESULT" not in out:
        raise ToolError(f"sem resultado: {out[-500:]}")
    return json.loads(out.split("\x1eRESULT", 1)[1])


def links(sid: str, names: list[str]) -> list[dict]:
    return [{"file": n, "url": ws.url(sid, n)} for n in names]


# ------------------------------------------------------------------ arquivos
@mcp.tool()
async def ingest_file(filename: str, data_base64: str, ctx: Context, mime_type: str = "") -> dict:
    """Salva um arquivo (base64) no workspace da conversa. O runtime do agente chama isto sozinho para cada anexo
    recebido (imagens, PDFs, planilhas…); conteúdo repetido é reaproveitado."""
    sid = sid_of(ctx)
    path, new = await asyncio.to_thread(ws.ingest, sid, filename, data_base64)
    return {"path": path.name, "new": new, "bytes": path.stat().st_size, "url": ws.url(sid, path.name)}


@mcp.tool()
async def list_files(ctx: Context) -> dict:
    """Lista os arquivos do workspace desta conversa (anexos recebidos e arquivos gerados) com links de download."""
    return {"files": await asyncio.to_thread(ws.listing, sid_of(ctx))}


@mcp.tool()
async def inspect_file(path: str, ctx: Context, max_rows: int = 10, pages: int = 5, ocr: bool = False) -> str:
    """Examina um arquivo do workspace: planilhas/CSV/Parquet/JSON (todas as abas: linhas, colunas, tipos, nulos,
    estatísticas e amostra), PDF (texto e tabelas por página), DOCX, PPTX, imagens e texto. ocr=true extrai texto de
    imagens e PDFs escaneados (Tesseract por+eng)."""
    return await kcall(sid_of(ctx), "inspect", timeout=240, path=path, max_rows=max_rows, pages=pages, ocr=ocr)


@mcp.tool()
async def get_file_link(path: str, ctx: Context) -> str:
    """Link de download (ou visualização, para HTML/imagens/PDF) de um arquivo do workspace."""
    sid = sid_of(ctx)
    if not ws.resolve(sid, path).exists():
        raise ToolError(f"{path} não existe")
    return ws.url(sid, path)


@mcp.tool()
async def delete_file(path: str, ctx: Context) -> str:
    """Apaga um arquivo do workspace."""
    p = ws.resolve(sid_of(ctx), path)
    if not p.is_file():
        raise ToolError(f"{path} não existe")
    p.unlink()
    return f"{path} apagado"


# ------------------------------------------------------------------ análise
@mcp.tool()
async def list_tables(ctx: Context) -> str:
    """Tabelas SQL disponíveis: cada CSV/TSV/Parquet/JSON vira uma view com o nome do arquivo (minúsculo, sem
    símbolos); cada aba de Excel vira <arquivo>_<aba>. Mostra colunas, tipos e contagem de linhas."""
    return await kcall(sid_of(ctx), "tables", timeout=180)


@mcp.tool()
async def run_sql(query: str, ctx: Context, max_rows: int = 50, save_as: str | None = None) -> str:
    """Executa SQL analítico (DuckDB) sobre os arquivos do workspace — use os nomes de list_tables. Suporta joins,
    window functions, PIVOT, QUALIFY, percentis etc. save_as='resultado.xlsx|.csv|.parquet|.json' grava o resultado
    completo como um novo arquivo (é assim que se entrega uma planilha editada)."""
    sid = sid_of(ctx)
    text = await kcall(sid, "sql", timeout=300, query=query, max_rows=max_rows, save_as=save_as)
    if save_as:
        text += f"\nDownload: {ws.url(sid, save_as)}"
    return text


@mcp.tool()
async def run_python(code: str, ctx: Context, timeout_s: int = 120) -> dict:
    """Executa Python num kernel Jupyter COM ESTADO (variáveis persistem na conversa). Diretório atual = workspace.
    Já importados: pd, np, duckdb, plt, con (duckdb). Disponíveis: scipy, sklearn, statsmodels, seaborn, plotly,
    openpyxl, pptx, docx, pdfplumber, PIL, pytesseract. Gráficos do matplotlib (plt.show()) viram PNG no workspace;
    arquivos salvos com caminho relativo (df.to_excel('saida.xlsx')) ganham link. Use print() para ver resultados."""
    sid = sid_of(ctx)
    before = await asyncio.to_thread(ws.snapshot, sid)
    k = await asyncio.to_thread(kernels.get, sid)
    r = await asyncio.to_thread(k.execute, code, max(5, min(timeout_s, 900)))
    r["files"] = await asyncio.to_thread(ws.changed, sid, before)
    return {k2: v for k2, v in r.items() if v not in (None, "", [])}


@mcp.tool()
async def reset_python(ctx: Context) -> str:
    """Reinicia o kernel Python desta conversa (limpa variáveis; os arquivos ficam)."""
    await asyncio.to_thread(kernels.reset, sid_of(ctx))
    return "kernel reiniciado"


# ------------------------------------------------------------------ entregáveis
@mcp.tool()
async def create_presentation(title: str, slides: list[dict], ctx: Context, subtitle: str | None = None,
                              theme: str = "light", accent: str | None = None, formats: list[str] | None = None,
                              filename: str | None = None, footer: str | None = None,
                              offline: bool | None = None) -> dict:
    """Cria apresentação 16:9 em PPTX (gráficos nativos editáveis) e/ou HTML (formats=['pptx','html']).
    theme: light | dark | corporate; accent: cor hex. slides: lista de objetos, um por slide:
    {type:'title', title, subtitle} | {type:'section', title} | {type:'bullets', title, bullets:['...','  sub-item']}
    | {type:'two_columns', title, left_title, left:[...], right_title, right:[...]}
    | {type:'chart', title, chart:{kind:'column|bar|stacked|line|area|pie|doughnut|scatter', categories:[...],
       series:[{name, values:[...]}]  OU  sql:'SELECT x, y1, y2 FROM ...', x:'x', y:['y1','y2']}, caption}
    | {type:'table', title, table:{columns, rows} OU {sql}, max_rows}
    | {type:'kpis', title, items:[{label, value OU sql, format:'int|dec|pct|brl|usd|brl_compact|compact', delta:'+12%'}]}
    | {type:'image', title, path:'figura_1.png', caption} | {type:'text', title, text}.
    Qualquer slide aceita notes (notas do apresentador). Os dados de sql vêm dos arquivos do workspace (DuckDB).
    offline=true embute a biblioteca de gráficos no HTML (abre sem internet; arquivo ~200 KB maior)."""
    sid = sid_of(ctx)
    spec = {"title": title, "subtitle": subtitle, "slides": slides, "theme": theme, "accent": accent,
            "formats": formats or ["pptx", "html"], "filename": filename, "footer": footer, "offline": offline}
    names = await kcall(sid, "presentation", timeout=300, spec=spec)
    return {"files": links(sid, names)}


@mcp.tool()
async def create_dashboard(title: str, ctx: Context, kpis: list[dict] | None = None, charts: list[dict] | None = None,
                           tables: list[dict] | None = None, insights: list[str] | None = None,
                           subtitle: str | None = None, theme: str = "light", accent: str | None = None,
                           filename: str | None = None, offline: bool | None = None) -> dict:
    """Cria um dashboard HTML interativo (Plotly: zoom, hover, exportar PNG; tabelas com filtro e ordenação).
    kpis: [{label, value OU sql (1 valor), format:'int|dec|pct|brl|usd|brl_compact|compact', delta}] —
          prefira *_compact para valores grandes (R$ 6,26 mi)
    charts: [{title, kind:'column|bar|stacked|line|area|pie|doughnut|scatter|heatmap', sql:'SELECT ...', x, y:[...]
             OU categories/series, width:1|2, x_title, y_title, note}]
    tables: [{title, sql OU columns/rows, max_rows}]; insights: frases com os achados principais.
    offline=true embute o Plotly no HTML (abre sem internet; arquivo ~3,5 MB maior)."""
    sid = sid_of(ctx)
    spec = {"title": title, "subtitle": subtitle, "kpis": kpis or [], "charts": charts or [], "tables": tables or [],
            "insights": insights or [], "theme": theme, "accent": accent, "filename": filename, "offline": offline}
    name = await kcall(sid, "dashboard", timeout=300, spec=spec)
    return {"file": name, "url": ws.url(sid, name)}


@mcp.tool()
async def create_document(title: str, markdown: str, ctx: Context, format: str = "docx",
                          filename: str | None = None) -> dict:
    """Gera um relatório a partir de markdown: format 'docx' (Word), 'html' ou 'md'. Linhas especiais:
    [[table: SELECT ...]] insere o resultado da consulta como tabela; [[image: figura_1.png]] insere uma imagem."""
    sid = sid_of(ctx)
    name = await kcall(sid, "document", timeout=240,
                       spec={"title": title, "markdown": markdown, "format": format, "filename": filename})
    return {"file": name, "url": ws.url(sid, name)}


@mcp.tool()
async def preview_file(path: str, ctx: Context, max_pages: int = 6):
    """Renderiza um PPTX, DOCX, XLSX ou PDF do workspace como imagens (LibreOffice), uma por slide/página, e as
    devolve para você VER o resultado: use depois de create_presentation/create_document para conferir layout,
    textos cortados ou sobrepostos, gráficos vazios. Também devolve os links dos PNGs."""
    from mcp.server.fastmcp import Image
    sid = sid_of(ctx)
    r = await kcall(sid, "preview", timeout=300, path=path, max_pages=max(1, min(max_pages, 12)))
    content = [json.dumps({"pages": r["pages"], "blank_pages": r["blank_pages"],
                           "files": links(sid, r["images"])}, ensure_ascii=False)]
    for name in r["images"][:4]:  # as imagens vão ao LLM (visão); limita para não estourar o contexto
        content.append(Image(data=await asyncio.to_thread(_thumb, ws.resolve(sid, name)), format="jpeg"))
    return content


def _thumb(p, width: int = 960) -> bytes:
    import io

    from PIL import Image as PILImage
    with PILImage.open(p) as im:
        im = im.convert("RGB")
        if im.width > width:
            im = im.resize((width, int(im.height * width / im.width)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return buf.getvalue()


# ------------------------------------------------------------------ web
def _check_host(url: str):
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ToolError("apenas URLs http(s)")
    if ALLOW_PRIVATE_FETCH:
        return
    for info in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80)):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ToolError(f"endereço interno bloqueado: {u.hostname}")


@mcp.tool()
async def fetch_url(url: str, ctx: Context, save_as: str | None = None) -> str:
    """Busca uma URL pública. Páginas HTML voltam como texto legível; arquivos (CSV, XLSX, PDF, imagens, JSON…)
    ou save_as são gravados no workspace para análise. Endereços internos/privados são bloqueados."""
    sid = sid_of(ctx)
    async with httpx.AsyncClient(timeout=60, follow_redirects=False,
                                 headers={"User-Agent": "Mozilla/5.0 (DataStudio; Agent Hangar)"}) as c:
        for _ in range(6):
            await asyncio.to_thread(_check_host, url)
            r = await c.get(url)
            if r.is_redirect and r.headers.get("location"):
                url = str(r.url.join(r.headers["location"]))
                continue
            break
    if r.status_code >= 400:
        raise ToolError(f"HTTP {r.status_code} em {url}")
    ctype = r.headers.get("content-type", "").split(";")[0].strip()
    if ctype in ("text/html", "application/xhtml+xml") and not save_as:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            tag.decompose()
        title = soup.title.get_text(strip=True) if soup.title else ""
        text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
        tables = len(soup.find_all("table"))
        hint = f"\n\n({tables} tabela(s) HTML — use run_python com pd.read_html)" if tables else ""
        return f"# {title}\n{url}\n\n{text[:20000]}{hint}"
    name = save_as or unquote(os.path.basename(urlparse(url).path)) or "download"
    if "." not in name:
        name += mimetypes.guess_extension(ctype) or ".bin"
    b64 = base64.b64encode(r.content).decode()
    path, _ = await asyncio.to_thread(ws.ingest, sid, name, b64)
    return f"Salvo como {path.name} ({len(r.content)/1024:.1f} KB, {ctype}). Download: {ws.url(sid, path.name)}"


# ------------------------------------------------------------------ downloads (porta pública)
INLINE = {"text/html", "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "application/pdf",
          "text/plain", "text/csv", "text/markdown", "application/json"}


async def serve_file(request: Request):
    sid, tok, rel = request.path_params["sid"], request.path_params["tok"], request.path_params["rel"]
    if not ws.verify(sid, tok):
        return PlainTextResponse("link inválido", 404)
    try:
        p = ws.resolve(sid, unquote(rel))
    except ValueError:
        return PlainTextResponse("link inválido", 404)
    if not p.is_file() or any(part.startswith(".") for part in p.relative_to(ws.workspace(sid)).parts):
        return PlainTextResponse("arquivo não encontrado", 404)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    inline = mime in INLINE
    headers = {"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "default-src 'self' data: blob: 'unsafe-inline' https://cdn.jsdelivr.net; "
                                          "img-src * data: blob:; connect-src 'none'"}
    return FileResponse(p, media_type=mime, headers=headers, filename=None if inline else p.name,
                        content_disposition_type="inline" if inline else "attachment")


async def health(_request: Request):
    return JSONResponse({"status": "ok", **kernels.status()})


files_app = Starlette(routes=[Route("/health", health), Route("/f/{sid}/{tok}/{rel:path}", serve_file)])


@mcp.custom_route("/health", methods=["GET"])
async def mcp_health(request: Request):
    return await health(request)


async def main():
    logging.basicConfig(level=logging.INFO)
    ws.SESSIONS.mkdir(parents=True, exist_ok=True)
    if kernels.SANDBOX == "container":
        from . import sandbox
        await asyncio.to_thread(sandbox.cleanup)
    servers = [uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(), host="0.0.0.0", port=8000, log_level="info")),
               uvicorn.Server(uvicorn.Config(files_app, host="0.0.0.0", port=8001, log_level="warning"))]
    await asyncio.gather(*(s.serve() for s in servers), _retention_loop())


if __name__ == "__main__":
    asyncio.run(main())
