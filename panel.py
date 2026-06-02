#!/usr/bin/env python3
import http.server, urllib.request, urllib.parse, json, subprocess, re, base64, secrets
import hmac, html, threading, time, os
from socketserver import ThreadingMixIn

CONFIG_PATH = "/etc/hysteria/config.yaml"
STATS_URL   = "http://127.0.0.1:9999/traffic"
HOST        = os.environ.get("PANEL_HOST", "your-domain.example.com")
PORT        = int(os.environ.get("PANEL_PORT", "443"))
SNI         = os.environ.get("PANEL_SNI", HOST)
PANEL_USER  = os.environ.get("PANEL_USER", "admin")
PANEL_PASS  = os.environ.get("PANEL_PASS", "")

if not PANEL_PASS:
    raise RuntimeError("PANEL_PASS environment variable is not set")

MAX_BODY     = 64 * 1024          # лимит тела запроса: 64 KB
RATE_WINDOW  = 60                 # окно для подсчёта попыток, сек
RATE_LIMIT   = 10                 # макс. неудачных попыток за окно
RATE_LOCKOUT = 300                # блокировка после превышения, сек

# CSRF-токен генерируется один раз при старте сервера
CSRF_TOKEN = secrets.token_hex(32)

# Лок для thread-safe записи конфига
_config_lock = threading.Lock()

# Rate limiting: {ip: [timestamp, ...]}
_rate_data: dict = {}
_rate_lock = threading.Lock()

# --- Rate limiting ---

def _check_rate(ip: str) -> bool:
    """Возвращает True если запрос разрешён, False если заблокирован."""
    now = time.time()
    with _rate_lock:
        attempts = _rate_data.get(ip, [])
        attempts = [t for t in attempts if now - t < RATE_WINDOW]
        if len(attempts) >= RATE_LIMIT:
            return False
        _rate_data[ip] = attempts
    return True

def _record_failure(ip: str):
    now = time.time()
    with _rate_lock:
        attempts = _rate_data.get(ip, [])
        attempts = [t for t in attempts if now - t < RATE_WINDOW]
        attempts.append(now)
        _rate_data[ip] = attempts

# --- Config ---

def read_users():
    text = open(CONFIG_PATH).read()
    block = re.search(r"userpass:\s*\n((?:[ \t]+\S.*\n?)+)", text)
    if not block:
        return {}
    users = {}
    for line in block.group(1).splitlines():
        m = re.match(r'[ \t]+(\S+):\s*["\']?([^"\']+)["\']?', line)
        if m:
            users[m.group(1)] = m.group(2).strip()
    return users

def write_users(users):
    with _config_lock:
        text = open(CONFIG_PATH).read()
        lines = "\n".join(f'    {u}: "{p}"' for u, p in users.items())
        new_auth = f"auth:\n  type: userpass\n  userpass:\n{lines}"
        text = re.sub(r"auth:.*?(?=\n\S|\Z)", new_auth, text, flags=re.DOTALL)
        open(CONFIG_PATH, "w").write(text)
    subprocess.run(["systemctl", "restart", "hysteria.service"], check=False)

def validate_username(name: str) -> bool:
    """Только буквы, цифры, дефис, подчёркивание. Длина 1-32."""
    return bool(re.fullmatch(r'[A-Za-z0-9_\-]{1,32}', name))

def get_traffic():
    try:
        r = urllib.request.urlopen(STATS_URL, timeout=2)
        return json.loads(r.read())
    except:
        return {}

def conn_str(user, pwd):
    return f"hysteria2://{user}:{pwd}@{HOST}:{PORT}?sni={SNI}#{user}"

def fmt_bytes(b):
    if not b: return "0 B"
    b = int(b)
    for unit in ["B","KB","MB","GB","TB"]:
        if b < 1024: return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"

# --- HTML ---

HTML = """<!DOCTYPE html>
<html lang=ru><head><meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Hysteria2 Panel</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px}}
h1{{font-size:1.4rem;margin-bottom:20px;color:#7dd3fc}}
table{{width:100%;border-collapse:collapse;margin-bottom:28px;font-size:.88rem}}
th{{background:#1e293b;padding:10px 14px;text-align:left;color:#94a3b8;font-weight:500}}
td{{padding:10px 14px;border-bottom:1px solid #1e293b22}}
tr:hover td{{background:#1e293b55}}
.badge{{display:inline-block;background:#0ea5e920;color:#7dd3fc;padding:2px 10px;border-radius:4px;font-size:.82rem;font-weight:600}}
.btn{{padding:5px 12px;border:none;border-radius:6px;cursor:pointer;font-size:.82rem;transition:.15s}}
.btn-del{{background:#ef444420;color:#f87171}}.btn-del:hover{{background:#ef444440}}
.btn-copy{{background:#0ea5e920;color:#7dd3fc}}.btn-copy:hover{{background:#0ea5e940}}
.form-row{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
input{{background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:8px 12px;border-radius:6px;font-size:.88rem;width:180px}}
input::placeholder{{color:#475569}}
.btn-add{{background:#22c55e20;color:#4ade80;padding:8px 16px}}.btn-add:hover{{background:#22c55e40}}
.dim{{color:#64748b;font-size:.82rem}}
.cstr{{font-size:.72rem;color:#94a3b8;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.toast{{position:fixed;bottom:24px;right:24px;background:#1e293b;padding:12px 18px;border-radius:8px;
  border:1px solid #334155;display:none;font-size:.85rem;color:#4ade80}}
.section{{color:#475569;font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}}
.btn-refresh{{background:#7c3aed20;color:#a78bfa;padding:7px 14px}}.btn-refresh:hover{{background:#7c3aed40}}
.btn-refresh.spin{{opacity:.6;pointer-events:none}}
#updated{{font-size:.75rem;color:#475569;margin-left:8px}}
.err{{color:#f87171;font-size:.82rem;margin-top:8px}}
</style></head><body>
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
  <h1 style="margin:0">&#128481; Hysteria2 Panel</h1>
  <button class="btn btn-refresh" onclick="doRefresh()" id=rbtn>&#8635; Обновить</button>
</div>
<p class=section>Пользователи</p>
<table><thead><tr>
  <th>Пользователь</th><th id=th-up>Upload</th><th id=th-dl>Download</th>
  <th>Строка подключения</th><th style="width:160px"></th>
</tr></thead><tbody>
{rows}
</tbody></table>
<p class=section>Добавить пользователя</p>
<form method=POST action=/add>
  <input type=hidden name=csrf value="{csrf}">
  <div class=form-row>
    <input name=username placeholder="Имя (a-z, 0-9, _, -)" required pattern="[A-Za-z0-9_\\-]{{1,32}}">
    <input name=password placeholder="Пароль (авто если пусто)">
    <button class="btn btn-add" type=submit>+ Добавить</button>
  </div>
</form>
<div class=toast id=toast>&#10003; Скопировано</div>
<script>
function copy(s){{
  navigator.clipboard.writeText(s).catch(()=>{{
    var ta=document.createElement('textarea');ta.value=s;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);
  }});
  var t=document.getElementById('toast');t.style.display='block';setTimeout(()=>t.style.display='none',2000);
}}
function fmtBytes(b){{
  b=parseInt(b)||0;
  var units=['B','KB','MB','GB','TB'];
  for(var i=0;i<units.length;i++){{if(b<1024)return b.toFixed(1)+' '+units[i];b/=1024;}}
  return b.toFixed(1)+' PB';
}}
function doRefresh(){{
  var btn=document.getElementById('rbtn');
  btn.classList.add('spin');btn.textContent='↻ Обновление...';
  fetch('/traffic').then(r=>r.json()).then(data=>{{
    for(var user in data){{
      var eu=document.getElementById('up-'+user),ed=document.getElementById('dl-'+user);
      if(eu)eu.textContent=fmtBytes(data[user].tx);
      if(ed)ed.textContent=fmtBytes(data[user].rx);
    }}
    var now=new Date();
    var ts=now.getHours().toString().padStart(2,'0')+':'+now.getMinutes().toString().padStart(2,'0')+':'+now.getSeconds().toString().padStart(2,'0');
    btn.textContent='↻ Обновить';btn.classList.remove('spin');
    var upd=document.getElementById('updated');
    if(!upd){{upd=document.createElement('span');upd.id='updated';btn.parentNode.appendChild(upd);}}
    upd.textContent='обновлено в '+ts;
  }}).catch(()=>{{btn.textContent='↻ Обновить';btn.classList.remove('spin');}});
}}
</script></body></html>"""

ROW = """<tr>
  <td><span class=badge>{user_h}</span></td>
  <td class=dim id="up-{user_h}">{up}</td><td class=dim id="dl-{user_h}">{dl}</td>
  <td><span class=cstr title="{cs_h}">{cs_h}</span></td>
  <td style="display:flex;gap:6px">
    <button class="btn btn-copy" data-cs="{cs_h}" onclick="copy(this.dataset.cs)">Копировать</button>
    <form method=POST action=/del style=display:inline>
      <input type=hidden name=csrf value="{csrf}">
      <input type=hidden name=username value="{user_h}">
      <button class="btn btn-del" type=submit>Удалить</button>
    </form>
  </td>
</tr>"""

def render(users, traffic):
    traffic_lower = {k.lower(): v for k, v in traffic.items()}
    rows = ""
    for user, pwd in users.items():
        tx  = traffic_lower.get(user.lower(), {})
        cs  = conn_str(user, pwd)
        rows += ROW.format(
            user_h = html.escape(user),
            up     = fmt_bytes(tx.get("tx", 0)),
            dl     = fmt_bytes(tx.get("rx", 0)),
            cs_h   = html.escape(cs),
            csrf   = CSRF_TOKEN,
        )
    return HTML.format(rows=rows, csrf=CSRF_TOKEN)

# --- HTTP Handler ---

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def client_ip(self):
        return self.client_address[0]

    def auth(self):
        ip = self.client_ip()
        if not _check_rate(ip):
            return False
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return False
        try:
            creds    = base64.b64decode(h[6:]).decode()
            expected = f"{PANEL_USER}:{PANEL_PASS}"
            ok = hmac.compare_digest(creds, expected)
        except Exception:
            ok = False
        if not ok:
            _record_failure(ip)
        return ok

    def require_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Hysteria2 Panel"')
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"Unauthorized")

    def send_html(self, html_body):
        b = html_body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Content-Length", len(b))
        self.end_headers()
        self.wfile.write(b)

    def bad_request(self, msg=b"Bad Request"):
        self.send_response(400)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg)

    def do_GET(self):
        if not self.auth():
            return self.require_auth()
        if self.path == "/traffic":
            traffic_lower = {k.lower(): v for k, v in get_traffic().items()}
            b = json.dumps(traffic_lower).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(b))
            self.end_headers()
            self.wfile.write(b)
            return
        self.send_html(render(read_users(), get_traffic()))

    def do_POST(self):
        if not self.auth():
            return self.require_auth()

        # Лимит размера тела
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            return self.bad_request(b"Request too large")

        data = urllib.parse.parse_qs(self.rfile.read(length).decode(errors="ignore"))

        # Проверка CSRF-токена
        token = data.get("csrf", [""])[0]
        if not hmac.compare_digest(token, CSRF_TOKEN):
            return self.bad_request(b"Invalid CSRF token")

        users = read_users()

        if self.path == "/add":
            uname = data.get("username", [""])[0].strip()
            pwd   = data.get("password",  [""])[0].strip() or secrets.token_urlsafe(18)
            if not validate_username(uname):
                return self.bad_request(b"Invalid username")
            users[uname] = pwd

        elif self.path == "/del":
            uname = data.get("username", [""])[0].strip()
            if not validate_username(uname):
                return self.bad_request(b"Invalid username")
            users.pop(uname, None)

        write_users(users)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    print("Hysteria2 Panel running on :8080")
    srv.serve_forever()
