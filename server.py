#!/usr/bin/env python3
"""BMOPS Dashboard Pro — Servidor con Sidebar AI"""
import http.server, urllib.request, urllib.error, urllib.parse, json, socket
from datetime import datetime, date
import pandas as pd
import sys
sys.path.insert(0, "/root/bmops-dashboard-v2")
from insight_engine import generate_insights

PORT = 8704
OPENROUTER_API_KEY = ""
GROQ_API_KEY = ""
FREELLMAPI_KEY = ""
DEEPSEEK_API_KEY = ""
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-v4-flash"
TELEGRAM_BOT_TOKEN = ""
# Load API keys from .env
# Load API keys from .env
for _ep in [os.environ.get("ENV_FILE", ".env")]:
    try:
        with open(_ep) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k == "OPENROUTER_API_KEY":
                        OPENROUTER_API_KEY = v
                    elif k == "GROQ_API_KEY":
                        GROQ_API_KEY = v
                    elif k == "FREELLMAPI_KEY":
                        FREELLMAPI_KEY = v
                    elif k == "DEEPSEEK_API_KEY":
                        DEEPSEEK_API_KEY = v
                    elif k == "DEEPSEEK_BASE_URL":
                        DEEPSEEK_BASE_URL = v
                    elif k == "TELEGRAM_BOT_TOKEN":
                        TELEGRAM_BOT_TOKEN = v
    except:
        pass

AIRTABLE_BASE = "appQDzUwnn6X84Dvh"
AIRTABLE_TABLE = "tbluYTpJTckXlhzFB"
TELEGRAM_BOT_TOKEN = "8969126879:AAEHTBf_evUjVH70RwatTWBFfKa7gLsR8_4"
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN", "")

def check_port(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        r = s.connect_ex(('127.0.0.1', port)) == 0
        s.close()
        return r
    except:
        return False

def check_telegram():
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe")
        return json.loads(urllib.request.urlopen(req, timeout=5).read()).get("ok", False)
    except:
        return False

def check_airtable():
    try:
        req = urllib.request.Request("https://api.airtable.com/v0/meta/bases")
        req.add_header("Authorization", f"Bearer {AIRTABLE_TOKEN}")
        urllib.request.urlopen(req, timeout=5)
        return True
    except urllib.error.HTTPError as e:
        return e.code == 403
    except:
        return False

def get_all_invoices():
    records = []
    try:
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{AIRTABLE_TABLE}?pageSize=100"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {AIRTABLE_TOKEN}")
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        records = data.get("records", [])
        cache_entries = [{"id": r["id"], "createdTime": r.get("createdTime",""), "fields": r.get("fields",{})} for r in records]
        with open("/root/bmops_facturas_cache.json", "w") as f:
            json.dump(cache_entries, f, indent=2, default=str)
    except:
        try:
            with open("/root/bmops_facturas_cache.json") as f:
                records = json.load(f)
        except:
            records = []
    today = date.today().isoformat()
    hoy = [r for r in records if r.get("createdTime", "")[:10] == today]
    return records, hoy

class Handler(http.server.BaseHTTPRequestHandler):
    def _call_llm(self, prompt, max_tokens=400):
        # FreeLLMAPI gateway local (:3010, auto-route) — fallback deepseek directo
        try:
            body = json.dumps({"model": "auto", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}).encode()
            req = urllib.request.Request("http://127.0.0.1:3010/v1/chat/completions", data=body, headers={
                "Authorization": f"Bearer {FREELLMAPI_KEY}", "Content-Type": "application/json"})
            resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
            return resp["choices"][0]["message"]["content"]
        except Exception:
            body = json.dumps({"model": DEEPSEEK_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}).encode()
            req = urllib.request.Request(DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions", data=body, headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"})
            resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
            return resp["choices"][0]["message"]["content"]

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        
        if path.rstrip("/") in ("/data-studio", "/studio"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open("/root/bmops_data_studio.html", "rb") as f:
                self.wfile.write(f.read())
            return
        
        if path.startswith("/datasets/"):
            filename = path.split("/datasets/", 1)[-1]
            try:
                with open(f"/root/datasets_demo/{filename}", "rb") as f:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.end_headers()
                    self.wfile.write(f.read())
            except:
                self.send_response(404); self.end_headers(); self.wfile.write(b"Not found")
            return
        
        if path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return
        if path == "/favicon.ico":
            self.send_response(204); self.end_headers(); return
        
        # Dashboard monitoring
        port_ok = check_port(8703)
        tg_ok = check_telegram()
        airtable_ok = check_airtable()
        all_ok = port_ok and tg_ok and airtable_ok
        recent, hoy = get_all_invoices()
        now = datetime.now().strftime("%d/%m/%Y · %H:%M")
        
        total_hoy = sum(float(r["fields"].get("Total", 0) or 0) for r in hoy)
        clientes_hoy = len(set(r["fields"].get("Razon Social", "").strip() for r in hoy if r["fields"].get("Razon Social", "").strip()))
        
        days = {}
        for r in recent:
            d = r.get("createdTime", "")[:10]
            t = float(r["fields"].get("Total", 0) or 0)
            days[d] = days.get(d, 0) + t
        chart_labels = sorted(days.keys())[-7:]
        chart_data = [days[d] for d in chart_labels]
        
        rows = ""
        for i, r in enumerate(recent[:15], 1):
            f = r.get("fields", {})
            rz = f.get("Razon Social", "—")[:28]
            rf = f.get("RIF", "—")[:14]
            nr = f.get("Factura Nro", "—")[:14]
            cp = f.get("Concepto", "—")[:35]
            t = f.get("Total", 0) or 0
            rows += f'<tr><td>{i}</td><td title="{f.get("Razon Social","")}">{rz}</td><td>{rf}</td><td>{nr}</td><td title="{f.get("Concepto","")}">{cp}</td><td class="num">{t:,.2f}</td></tr>'
        
        srv = '<span class="badge on">ONLINE</span>' if port_ok else '<span class="badge off">OFFLINE</span>'
        tgb = '<span class="badge on">ACTIVO</span>' if tg_ok else '<span class="badge off">CAIDO</span>'
        atb = '<span class="badge on">CONECTADO</span>' if airtable_ok else '<span class="badge off">SIN CONEXION</span>'
        status = '<span class="pulse on"></span> Operativo' if all_ok else '<span class="pulse off"></span> Degradado'
        
        html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BMOPS · Dashboard</title>
<style>
:root{{--bg:#0a0a0f;--card:#111118;--border:#1e1e2e;--text:#a0a0b8;--head:#e8e8f0;--accent:#6366f1;--green:#22c55e;--red:#ef4444;--amber:#f59e0b;--blue:#3b82f6;--radius:12px}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.5}}
.container{{max-width:1200px;margin:0 auto;padding:24px 20px}}
.header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}}
.header h1{{font-size:1.4em;font-weight:700;color:var(--head)}}.header h1 span{{color:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:24px}}
.stat{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px}}
.stat .icon{{font-size:1.4em;margin-bottom:8px}}
.stat .value{{font-size:1.8em;font-weight:700;color:var(--head)}}
.stat .label{{font-size:.78em;color:var(--text);text-transform:uppercase;letter-spacing:.04em}}
.section{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:18px}}
.section h2{{font-size:.9em;font-weight:600;color:var(--head);margin-bottom:16px}}
.status-bar{{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--border);border-radius:20px;padding:6px 16px;font-size:.8em}}
.pulse{{width:8px;height:8px;border-radius:50%;display:inline-block;animation:pulse 2s infinite}}
.pulse.on{{background:var(--green);box-shadow:0 0 6px var(--green)}}
.pulse.off{{background:var(--red);box-shadow:0 0 6px var(--red)}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;padding:10px 8px;font-size:.72em;text-transform:uppercase;color:var(--text);border-bottom:1px solid var(--border)}}
td{{padding:9px 8px;border-bottom:1px solid rgba(30,30,46,.6);font-size:.82em}}
tr:hover td{{background:rgba(99,102,241,.06)}}
td.num{{text-align:right;font-weight:600;color:var(--head)}}
.svc{{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:8px}}
.badge{{font-size:.72em;font-weight:700;padding:3px 10px;border-radius:6px}}
.badge.on{{background:rgba(34,197,94,.12);color:var(--green);border:1px solid rgba(34,197,94,.25)}}
.badge.off{{background:rgba(239,68,68,.12);color:var(--red);border:1px solid rgba(239,68,68,.25)}}
</style>
</head>
<body>
<div class="container">
<div class="header"><h1>BMOPS<span> Dashboard</span></h1><div style="text-align:right;font-size:.8em">{now}<br>Auto-refresh 45s</div></div>
<div class="status-bar">{status}</div>
<div class="grid">
<div class="stat"><div class="icon">🧾</div><div class="value">{len(recent)}</div><div class="label">Total facturas</div></div>
<div class="stat"><div class="icon">📅</div><div class="value">{len(hoy)}</div><div class="label">Hoy</div></div>
<div class="stat"><div class="icon">💰</div><div class="value">Bs.{total_hoy:,.0f}</div><div class="label">Total hoy</div></div>
<div class="stat"><div class="icon">🏢</div><div class="value">{clientes_hoy}</div><div class="label">Clientes hoy</div></div>
</div>
<div class="section"><h2>📈 Ultimos 7 dias</h2>
<div style="height:220px"><canvas id="chart"></canvas></div></div>
<div class="section"><h2>📡 Servicios</h2>
<div class="svc"><span>Bot Facturas</span>{srv}</div>
<div class="svc"><span>Telegram Bot</span>{tgb}</div>
<div class="svc"><span>Airtable</span>{atb}</div></div>
<div class="section"><h2>📋 Ultimas facturas</h2>
<div style="overflow-x:auto"><table><tr><th>#</th><th>Razon Social</th><th>RIF</th><th>Nro</th><th>Concepto</th><th class="num">Total</th></tr>{rows}</table></div></div>
<div class="footer" style="text-align:center;color:#333;font-size:.72em;padding:20px">BMOPS Monitoring System</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
new Chart(document.getElementById('chart'),{{type:'bar',data:{{labels:{json.dumps([d[-5:] for d in chart_labels])},datasets:[{{label:'Bs.',data:{json.dumps(chart_data)},backgroundColor:'rgba(99,102,241,.7)',borderRadius:6}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{grid:{{display:false}},ticks:{{color:'#a0a0b8'}}}},y:{{grid:{{color:'#1e1e2e'}},ticks:{{color:'#a0a0b8'}}}}}}}}}});
</script>
</body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.rstrip("/").endswith("/analyze-full"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                headers = body.get("headers", [])
                raw_data = body.get("rawData", [])
                filters = body.get("filters", {})
                total_rows = body.get("totalRows", 0)
                total_unfiltered = body.get("totalUnfiltered", total_rows)
                
                if raw_data and len(raw_data) > 0:
                    df = pd.DataFrame(raw_data, columns=headers)
                    result = generate_insights(df, filters=filters, total_count=total_unfiltered)
                    prompt = result["prompt"]
                    
                    analysis = self._call_llm(prompt, 1500)
                    analysis = analysis.replace("```html", "").replace("```", "").strip()
                    
                    # Build metric summary from result
                    metrics = result.get("metrics", {})
                    data_type = metrics.get("data_type", "financial")
                    
                    # Generate infographics HTML
                    infographics = []
                    
                    if data_type == "qualitative":
                        qual = metrics.get("qualitative", {})
                        for col in qual.get("columns_analyzed", [])[:3]:
                            if col.get("type") == "text" and "top5" in col:
                                items = list(col["top5"].items())[:5]
                                max_val = max(col["top5"].values()) if col["top5"] else 1
                                bars = "".join(
                                    f'<div class="inf-bar"><span class="inf-label">{k}</span><div class="inf-track"><div class="inf-fill" style="width:{v/max_val*100}%;background:#{hash(k)%0xffffff:06x}"></div></div><span class="inf-num">{v}</span></div>'
                                    for k, v in items
                                )
                                infographics.append(f'<div class="inf-section"><h4>Distribución: {col["name"]}</h4>{bars}</div>')
                    else:
                        c = metrics.get("concentration")
                        if c:
                            share = c.get("top3_share_of_value", 0)
                            risk_color = "#ef4444" if c.get("is_high_risk") else "#22c55e"
                            infographics.append(
                                f'<div class="inf-section"><h4>Concentración</h4>'
                                f'<div class="inf-ring"><svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="50" fill="none" stroke="#1e1e2e" stroke-width="12"/>'
                                f'<circle cx="60" cy="60" r="50" fill="none" stroke="{risk_color}" stroke-width="12" stroke-dasharray="{share*3.14} {100*3.14}" transform="rotate(-90 60 60)"/></svg>'
                                f'<div class="inf-ring-text">{share}%</div></div>'
                                f'<div class="inf-detail">Top 3: {", ".join(c.get("top3_entities",[])[:3])}</div></div>'
                            )
                        a = metrics.get("anomaly")
                        if a and a.get("has_anomalies"):
                            count = a.get("anomaly_count", 0)
                            infographics.append(
                                f'<div class="inf-section"><h4>Anomalías</h4>'
                                f'<div class="inf-badge-warn">⚠️ {count} periodo(s) atípico(s)</div>'
                                f'<div class="inf-detail">Mayor: {a.get("most_significant_period")} ({a.get("direction","")})</div></div>'
                            )
                        t = metrics.get("trend")
                        if t:
                            pct = t.get("trend_change_pct", 0)
                            direction = t.get("direction", "estable")
                            trend_color = "#22c55e" if pct > 0 else "#ef4444"
                            arrow = "📈" if pct > 0 else "📉"
                            infographics.append(
                                f'<div class="inf-section"><h4>Tendencia</h4>'
                                f'<div class="inf-badge" style="color:{trend_color};border-color:{trend_color}">{arrow} {pct}% ({direction})</div>'
                                f'<div class="inf-detail">Últimos 3 meses: ${t.get("recent_3month_avg",0):,.2f} vs histórico: ${t.get("historical_avg",0):,.2f}</div></div>'
                            )
                    
                    infographics_html = "".join(infographics) if infographics else "<p class='text-muted text-sm'>No hay suficientes datos para mostrar infografía</p>"
                    
                    # Wrap in HTML with infographics
                    html = f"""<div class="section"><h3>🔍 Insights Generados</h3><div class="content">{analysis}</div></div>
                    <div class="section"><h3>📊 Infografía de Métricas</h3><div class="inf-grid">{infographics_html}</div></div>"""
                    
                    # Add metrics detail (collapsible for transparency)
                    metrics = result.get("metrics", {})
                    details = []
                    if metrics.get("concentration"):
                        c = metrics["concentration"]
                        risk = "⚠️ Alto riesgo" if c.get("is_high_risk") else "✅ Riesgo moderado"
                        details.append(f"<p><strong>Concentración:</strong> Top 3 ({', '.join(c.get('top3_entities',[]))}) = {c.get('top3_share_of_value',0)}% del total · {risk}</p>")
                    if metrics.get("anomaly"):
                        a = metrics["anomaly"]
                        if a.get("has_anomalies"):
                            details.append(f"<p><strong>Anomalías:</strong> {a.get('anomaly_count',0)} periodos atípicos detectados · El más significativo: {a.get('most_significant_period')} ({a.get('direction','')})</p>")
                        else:
                            details.append(f"<p><strong>Anomalías:</strong> Sin anomalías significativas detectadas</p>")
                    if metrics.get("trend"):
                        t = metrics["trend"]
                        details.append(f"<p><strong>Tendencia:</strong> Promedio últimos 3 meses vs histórico: {t.get('trend_change_pct',0)}% ({t.get('direction','estable')})</p>")
                    if metrics.get("actionable_delta"):
                        d = metrics["actionable_delta"]
                        details.append(f"<p><strong>Oportunidad:</strong> Si '{d.get('entity_with_biggest_increase','')}' recupera su nivel anterior, impacto de ${d.get('increase_amount',0):,.2f}</p>")
                    
                    html += f"""<div class="section"><h3>📊 Métricas Calculadas</h3><div class="content" style="font-size:.8rem;color:#a0a0b8">{''.join(details)}</div></div>"""
                else:
                    # Fallback: old behavior with summary
                    summary_text = "\\n".join(body.get("summary", ["Sin datos"]))
                    prompt = f"""Eres un analista de datos senior. Genera un informe ejecutivo en HTML con estos datos: {summary_text}. Idioma: español. Tono ejecutivo. Máximo 200 palabras."""
                    analysis = self._call_llm(prompt, 600)
                    analysis = analysis.replace("```html", "").replace("```", "").strip()
                    html = f"""<div class="section"><h3>🔍 Resumen</h3><div class="content">{analysis}</div></div>"""
                
                self._json(200, {"analysis": html})
            except Exception as e:
                import traceback
                self._json(500, {"error": str(e) + "\\n" + traceback.format_exc()})
            return
        
        if path.rstrip("/").endswith("/analyze"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                analysis = self._call_llm(body.get("title", ""), body.get("labels", []), body.get("values", []))
                self._json(200, {"analysis": analysis})
            except Exception as e:
                self._json(500, {"error": str(e)})
            return
        self.send_response(404)
        self.end_headers()

if __name__ == "__main__":
    srv = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"BMOPS Dashboard Pro → http://0.0.0.0:{PORT}")
    srv.serve_forever()
