"""Apresentação HTML de arquivo único (16:9, setas/teclado/clique, tela cheia com F) com gráficos Chart.js."""
import base64
import html
import json
import mimetypes
from pathlib import Path

from .common import chart_data, filename, fmt, scalar, table_data, theme

CSS = """
*{box-sizing:border-box;margin:0}html,body{height:100%;background:#000;font-family:Inter,system-ui,Segoe UI,sans-serif}
.deck{height:100%;display:flex;align-items:center;justify-content:center}
.slide{display:none;width:min(100vw,177.78vh);aspect-ratio:16/9;background:var(--bg);color:var(--fg);padding:5% 6%;
 position:relative;overflow:hidden;flex-direction:column}
.slide.on{display:flex}.slide.dark{background:var(--accent);color:#fff;justify-content:center}
h1{font-size:clamp(28px,5vw,64px);line-height:1.1}h2{font-size:clamp(20px,2.6vw,38px);margin-bottom:3%;
 border-left:.35em solid var(--accent);padding-left:.5em}.dark h2{border:0;padding:0;font-size:clamp(26px,4vw,52px)}
.sub{font-size:clamp(14px,1.8vw,26px);opacity:.85;margin-top:2%}
ul{font-size:clamp(14px,1.7vw,26px);line-height:1.5;padding-left:1.2em}li{margin:.35em 0}li.l1{margin-left:1.4em;color:var(--muted);font-size:.85em}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:5%;flex:1}.cols h3{color:var(--accent);margin-bottom:.4em;font-size:clamp(14px,1.6vw,24px)}
.chart{flex:1;min-height:0;position:relative}.cap{color:var(--muted);font-size:clamp(11px,1.1vw,17px);margin-top:1%}
table{border-collapse:collapse;width:100%;font-size:clamp(10px,1.1vw,17px)}th{background:var(--accent);color:#fff;text-align:left}
th,td{padding:.45em .7em}tr:nth-child(even) td{background:var(--card)}
.kpis{display:flex;gap:3%;flex:1;align-items:center}.kpi{flex:1 1 0;min-width:0;background:var(--card);border-radius:18px;padding:5% 3%;text-align:center}
.kpi b{display:block;font-size:clamp(18px,2.6vw,44px);color:var(--accent);white-space:nowrap}.kpi span{font-size:clamp(12px,1.4vw,22px)}
.kpi i{display:block;font-style:normal;font-weight:700;margin-top:.4em}.up{color:#059669}.down{color:#DC2626}
.img{flex:1;display:flex;justify-content:center;min-height:0}.img img{max-width:100%;max-height:100%;object-fit:contain}
.txt{font-size:clamp(14px,1.8vw,28px);line-height:1.5;white-space:pre-wrap}
.foot{position:absolute;bottom:3%;left:6%;right:6%;display:flex;justify-content:space-between;color:var(--muted);font-size:clamp(9px,.9vw,14px)}
.dark .foot{color:#E0E7FF}.nav{position:fixed;bottom:12px;right:16px;display:flex;gap:8px}
.nav button{background:#ffffff22;color:#fff;border:1px solid #ffffff44;border-radius:8px;padding:6px 12px;cursor:pointer}
"""

JS = """
const S=[...document.querySelectorAll('.slide')];let i=0;const drawn=new Set();
function show(n){i=Math.max(0,Math.min(S.length-1,n));S.forEach((s,k)=>s.classList.toggle('on',k===i));draw(i);location.hash=i+1}
function draw(k){if(drawn.has(k))return;drawn.add(k);S[k].querySelectorAll('canvas[data-c]').forEach(c=>{
 const d=JSON.parse(c.dataset.c);if(window.Chart)new Chart(c,d);})}
document.addEventListener('keydown',e=>{if(['ArrowRight','PageDown',' '].includes(e.key))show(i+1);
 if(['ArrowLeft','PageUp'].includes(e.key))show(i-1);if(e.key==='f')document.documentElement.requestFullscreen?.()});
document.querySelector('.deck').addEventListener('click',e=>{if(e.target.closest('canvas,a,table'))return;
 show(i+(e.clientX>innerWidth/2?1:-1))});
window.addEventListener('load',()=>show((parseInt(location.hash.slice(1))||1)-1));
"""


def e(x):
    return html.escape(str(x))


def _chart_cfg(ch, q, t):
    kind = ch.get("kind", "column")
    cats, series = chart_data(ch, q)
    typ = {"column": "bar", "bar": "bar", "stacked": "bar", "line": "line", "area": "line", "pie": "pie",
           "doughnut": "doughnut", "scatter": "scatter"}.get(kind, "bar")
    pal = ["#" + c for c in t["palette"]]
    ds = []
    for i, s in enumerate(series[:1] if typ in ("pie", "doughnut") else series):
        color = pal if typ in ("pie", "doughnut") else pal[i % len(pal)]
        d = {"label": s["name"], "data": s["values"], "backgroundColor": color, "borderColor": color,
             "fill": kind == "area", "tension": .3}
        if typ == "scatter":
            d["data"] = [{"x": float(x), "y": y} for x, y in zip(cats, s["values"], strict=False)
                         if _isnum(x) and y is not None]
        ds.append(d)
    opts = {"responsive": True, "maintainAspectRatio": False,
            "plugins": {"legend": {"display": len(ds) > 1 or typ in ("pie", "doughnut"),
                                   "labels": {"color": "#" + t["fg"]}}}}
    if typ not in ("pie", "doughnut"):
        axis = {"ticks": {"color": "#" + t["muted"]}, "grid": {"color": "#" + t["muted"] + "33"}}
        opts["scales"] = {"x": dict(axis, stacked=kind == "stacked"), "y": dict(axis, stacked=kind == "stacked")}
        if kind == "bar":
            opts["indexAxis"] = "y"
    return {"type": typ, "data": {"labels": cats if typ != "scatter" else None, "datasets": ds}, "options": opts}


def _isnum(x):
    try:
        float(x)
        return True
    except ValueError:
        return False


def build(spec: dict, base: Path, stem: str, q) -> str:
    t = theme(spec)
    title = spec.get("title", "Apresentação")
    slides = list(spec.get("slides") or [])
    if not slides or slides[0].get("type") != "title":
        slides.insert(0, {"type": "title"})
    parts = []
    for n, sl in enumerate(slides, 1):
        kind = sl.get("type", "bullets")
        dark = kind in ("title", "section")
        body = ""
        if kind == "title":
            body = f"<h1>{e(sl.get('title') or title)}</h1>"
            sub = sl.get("subtitle") or spec.get("subtitle")
            body += f"<div class=sub>{e(sub)}</div>" if sub else ""
        elif kind == "section":
            body = f"<h2>{e(sl.get('title', ''))}</h2>"
        else:
            body = f"<h2>{e(sl.get('title', ''))}</h2>"
            if kind == "bullets":
                body += "<ul>" + "".join(
                    f"<li class={'l1' if str(b).startswith(('  ', '- ')) else 'l0'}>{e(str(b).lstrip(' -'))}</li>"
                    for b in sl.get("bullets", [])) + "</ul>"
            elif kind == "two_columns":
                cols = []
                for side in ("left", "right"):
                    h3 = f"<h3>{e(sl[side + '_title'])}</h3>" if sl.get(side + "_title") else ""
                    cols.append(f"<div>{h3}<ul>" + "".join(f"<li>{e(b)}</li>" for b in sl.get(side, [])) + "</ul></div>")
                body += f"<div class=cols>{''.join(cols)}</div>"
            elif kind == "chart":
                cfg = json.dumps(_chart_cfg(sl.get("chart") or {}, q, t), ensure_ascii=False)
                body += f"<div class=chart><canvas data-c='{e(cfg)}'></canvas></div>"
                body += f"<div class=cap>{e(sl['caption'])}</div>" if sl.get("caption") else ""
            elif kind == "table":
                cols, rows = table_data(sl.get("table") or sl, q, limit=int(sl.get("max_rows", 15)))
                body += "<table><tr>" + "".join(f"<th>{e(c)}</th>" for c in cols) + "</tr>" + "".join(
                    "<tr>" + "".join(f"<td>{e(fmt(v) if isinstance(v, (int, float)) else v)}</td>" for v in r) + "</tr>"
                    for r in rows) + "</table>"
            elif kind == "kpis":
                cards = []
                for it in sl.get("items", [])[:6]:
                    d = str(it.get("delta", ""))
                    di = f"<i class={'down' if d.strip().startswith('-') else 'up'}>{e(d)}</i>" if d else ""
                    cards.append(f"<div class=kpi><b>{e(fmt(scalar(it, q), it.get('format')))}</b>"
                                 f"<span>{e(it.get('label', ''))}</span>{di}</div>")
                body += f"<div class=kpis>{''.join(cards)}</div>"
            elif kind == "image":
                p = base / sl.get("path", "")
                if p.exists():
                    mime = mimetypes.guess_type(p.name)[0] or "image/png"
                    b64 = base64.b64encode(p.read_bytes()).decode()
                    body += f"<div class=img><img src='data:{mime};base64,{b64}' alt=''></div>"
                body += f"<div class=cap>{e(sl['caption'])}</div>" if sl.get("caption") else ""
            else:
                body += f"<div class=txt>{e(sl.get('text', ''))}</div>"
        foot = f"<div class=foot><span>{e(spec.get('footer') or title)}</span><span>{n}/{len(slides)}</span></div>"
        notes = f"<!-- notas: {e(sl['notes'])} -->" if sl.get("notes") else ""
        parts.append(f"<section class='slide{' dark' if dark else ''}'>{body}{foot}{notes}</section>")
    root = ";".join(f"--{k}:#{t[k]}" for k in ("bg", "fg", "muted", "accent", "card"))
    doc = (f"<!doctype html><html lang=pt-BR><head><meta charset=utf-8><meta name=viewport content='width=device-width,"
           f"initial-scale=1'><title>{e(title)}</title><style>:root{{{root}}}{CSS}</style>"
           "<script src='https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js'></script></head><body>"
           f"<div class=deck>{''.join(parts)}</div><div class=nav><button onclick='show(i-1)'>◀</button>"
           f"<button onclick='show(i+1)'>▶</button></div><script>{JS}</script></body></html>")
    name = filename(stem, ".html")
    (base / name).write_text(doc, encoding="utf-8")
    return name
