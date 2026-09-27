"""Dashboard HTML interativo de arquivo único: KPIs, gráficos Plotly (zoom/hover/export PNG), tabelas com busca e
ordenação, e insights em texto. Os dados vão embutidos no arquivo — abre offline, exceto a lib do Plotly (CDN)."""
import html
import json
from pathlib import Path

from .common import chart_data, filename, fmt, lib_tag, scalar, table_data, theme

CSS = """
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,Segoe UI,sans-serif;background:var(--bg2);color:var(--fg)}
header{padding:28px 32px 8px}h1{margin:0;font-size:26px}.sub{color:var(--muted);margin-top:4px}
main{padding:12px 32px 40px;display:grid;gap:16px}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
.card{background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:16px 18px;min-width:0}
.kpi{container-type:inline-size}.kpi b{display:block;font-size:clamp(14px,9.5cqi,28px);color:var(--accent);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.kpi span{color:var(--muted);font-size:13px}
.kpi i{font-style:normal;font-weight:700;font-size:13px;margin-left:6px}.up{color:#059669}.down{color:#DC2626}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.w2{grid-column:1/-1}
h2{font-size:15px;margin:0 0 8px}.plot{height:340px}.note{color:var(--muted);font-size:13px;margin-top:6px}
.tbl input{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;margin-bottom:8px;background:var(--bg);color:var(--fg)}
.tbl .wrap{max-height:420px;overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th{position:sticky;top:0;background:var(--accent);color:#fff;text-align:left;cursor:pointer;white-space:nowrap}
th,td{padding:7px 10px;border-bottom:1px solid var(--line)}td.n{text-align:right;font-variant-numeric:tabular-nums}
.ins li{margin:6px 0;line-height:1.5}footer{color:var(--muted);font-size:12px;padding:0 32px 24px}
@media(max-width:860px){.grid{grid-template-columns:1fr}main,header{padding-left:16px;padding-right:16px}}
"""

JS = """
const P=window.__P;const dark=P.dark;
for(const [id,fig] of Object.entries(P.figs)){fig.layout=Object.assign({margin:{t:10,r:10,b:40,l:10},paper_bgcolor:'rgba(0,0,0,0)',
 plot_bgcolor:'rgba(0,0,0,0)',font:{color:P.fg},colorway:P.pal,legend:{orientation:'h',y:-0.2},
 xaxis:{gridcolor:P.grid,automargin:true},yaxis:{gridcolor:P.grid,automargin:true}},fig.layout||{});
 if(window.Plotly)Plotly.newPlot(id,fig.data,fig.layout,{responsive:true,displaylogo:false});}
document.querySelectorAll('.tbl').forEach(box=>{const rows=[...box.querySelectorAll('tbody tr')];
 box.querySelector('input').addEventListener('input',e=>{const q=e.target.value.toLowerCase();
  rows.forEach(r=>r.style.display=r.innerText.toLowerCase().includes(q)?'':'none')});
 box.querySelectorAll('th').forEach((th,k)=>{let asc=true;th.onclick=()=>{const tb=box.querySelector('tbody');
  rows.sort((a,b)=>{const x=a.children[k].dataset.v,y=b.children[k].dataset.v;const nx=parseFloat(x),ny=parseFloat(y);
   const c=(!isNaN(nx)&&!isNaN(ny))?nx-ny:String(x).localeCompare(String(y));return asc?c:-c});asc=!asc;
  rows.forEach(r=>tb.appendChild(r))}})});
"""


def e(x):
    return html.escape(str(x))


def _fig(ch, q):
    kind = ch.get("kind", "column")
    cats, series = chart_data(ch, q)
    data = []
    for s in series:
        if kind in ("pie", "doughnut"):
            data.append({"type": "pie", "labels": cats, "values": s["values"], "hole": .5 if kind == "doughnut" else 0,
                         "name": s["name"]})
            break
        if kind == "scatter":
            data.append({"type": "scatter", "mode": "markers", "x": cats, "y": s["values"], "name": s["name"]})
        elif kind in ("line", "area"):
            data.append({"type": "scatter", "mode": "lines+markers", "x": cats, "y": s["values"], "name": s["name"],
                         "fill": "tozeroy" if kind == "area" else None})
        elif kind == "bar":
            data.append({"type": "bar", "orientation": "h", "y": cats, "x": s["values"], "name": s["name"]})
        elif kind == "heatmap":
            data.append({"type": "heatmap", "x": cats, "y": [x["name"] for x in series],
                         "z": [x["values"] for x in series]})
            break
        else:
            data.append({"type": "bar", "x": cats, "y": s["values"], "name": s["name"]})
    layout = {"barmode": "stack"} if kind == "stacked" else {}
    if ch.get("x_title"):
        layout["xaxis"] = {"title": {"text": ch["x_title"]}, "automargin": True}
    if ch.get("y_title"):
        layout["yaxis"] = {"title": {"text": ch["y_title"]}, "automargin": True}
    return {"data": data, "layout": layout}


def build(spec: dict, base: Path, q) -> str:
    t = theme(spec)
    dark = spec.get("theme") == "dark"
    title = spec.get("title", "Dashboard")
    figs, blocks = {}, []
    kpis = []
    for it in spec.get("kpis", []):
        d = str(it.get("delta", ""))
        di = f"<i class={'down' if d.strip().startswith('-') else 'up'}>{e(d)}</i>" if d else ""
        kpis.append(f"<div class='card kpi'><b>{e(fmt(scalar(it, q), it.get('format')))}</b>"
                    f"<span>{e(it.get('label', ''))}</span>{di}</div>")
    for i, ch in enumerate(spec.get("charts", [])):
        fid = f"f{i}"
        figs[fid] = _fig(ch, q)
        note = f"<div class=note>{e(ch['note'])}</div>" if ch.get("note") else ""
        blocks.append(f"<div class='card {'w2' if ch.get('width') == 2 else ''}'><h2>{e(ch.get('title', ''))}</h2>"
                      f"<div id={fid} class=plot></div>{note}</div>")
    for tb in spec.get("tables", []):
        cols, rows = table_data(tb, q, limit=int(tb.get("max_rows", 500)))
        head = "".join(f"<th>{e(c)} ⇅</th>" for c in cols)
        body = "".join("<tr>" + "".join(
            f"<td class=n data-v='{v}'>{e(fmt(v))}</td>" if isinstance(v, (int, float)) and not isinstance(v, bool)
            else f"<td data-v='{e(v)}'>{e(v)}</td>" for v in r) + "</tr>" for r in rows)
        blocks.append(f"<div class='card tbl w2'><h2>{e(tb.get('title', 'Tabela'))}</h2><input placeholder='Filtrar…'>"
                      f"<div class=wrap><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></div>")
    ins = spec.get("insights") or []
    ins_html = ("<div class='card w2 ins'><h2>Principais achados</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in ins)
                + "</ul></div>") if ins else ""
    sub_html = f"<div class=sub>{e(spec['subtitle'])}</div>" if spec.get("subtitle") else ""
    kpis_html = f"<div class=kpis>{''.join(kpis)}</div>" if kpis else ""
    bg2 = "0B1120" if dark else "F5F6F8"
    line = "334155" if dark else "E5E7EB"
    root = (f"--bg:#{t['bg'] if not dark else '111827'};--bg2:#{bg2};--fg:#{t['fg']};--muted:#{t['muted']};"
            f"--accent:#{t['accent']};--line:#{line}")
    payload = {"figs": figs, "dark": dark, "fg": "#" + t["fg"], "grid": "#" + line,
               "pal": ["#" + c for c in t["palette"]]}
    doc = (f"<!doctype html><html lang=pt-BR><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
           f"initial-scale=1'><title>{e(title)}</title><style>:root{{{root}}}{CSS}</style>"
           f"{lib_tag('plotly', spec.get('offline'))}</head><body>"
           f"<header><h1>{e(title)}</h1>{sub_html}</header>"
           f"<main>{kpis_html}{ins_html}"
           f"<div class=grid>{''.join(blocks)}</div></main>"
           f"<footer>{e(spec.get('footer', 'Gerado pelo Data Studio · Agent Hangar'))}</footer>"
           f"<script>window.__P={json.dumps(payload, ensure_ascii=False, default=str)}</script><script>{JS}</script>"
           "</body></html>")
    name = filename(spec.get("filename") or title, ".html")
    (base / name).write_text(doc, encoding="utf-8")
    return name
