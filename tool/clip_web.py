#!/usr/bin/env python3
"""
Contact Sheet - LAN page
========================
A small page you open on your phone (same Wi-Fi) to see clip status and to start an upload or a
Google Drive archive on the PC. First step only: it is NOT reachable from the internet.

    py -3 clip_web.py            start it; it prints a link with a random one-time token
    py -3 clip_web.py --hours 2  stop by itself after 2 hours (default 4)

Safety rules built in:
    * Listens only on this PC's private LAN address (192.168.x.x, 10.x.x.x, 172.16-31.x.x), never on
      0.0.0.0 and never on a public address. It refuses to start if it cannot find one.
    * Every request needs the random token in the link. The token changes each time it starts.
    * Nothing starts from one tap. You press "Preview", read exactly what would happen (it is the
      pipeline's own --dry-run), type UPLOAD or ARCHIVE, and press the final button. The server
      re-checks that the preview has not changed before it runs.
    * Uploads stay UNLISTED (the pipeline hard-codes that). Archive only copies and checks MD5;
      it never deletes. There is no publish button: making a video public is only possible at the PC.
    * Only one job at a time, and never while another upload/archive is already running.
    * The page serves no files from your disk, loads nothing from the internet and sets no cookies.

Before ever exposing this beyond your home network, put it behind a tunnel with a real login
(for example Cloudflare Tunnel with Access). The token alone is not enough for the internet.
"""

import argparse
import collections
import csv
import hmac
import ipaddress
import json
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
MANIFEST = BASE / "manifest.csv"
PIPELINE = BASE / "clip_pipeline.py"
ACTIONS = {"upload": "UPLOAD", "archive": "ARCHIVE"}      # action -> word you must type
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STATE = {"token": "", "host": "", "job": None, "plans": {}, "bad": 0, "lock": threading.Lock()}

# --------------------------------------------------------------------------- helpers


def lan_ip():
    """This PC's private LAN address, or None. (A UDP connect sends no packet; it just picks the route.)"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        return None
    a = ipaddress.ip_address(ip)
    return ip if a.is_private and not a.is_loopback and not a.is_link_local else None


def read_manifest():
    for _ in range(5):                      # the pipeline swaps the file in; retry if we catch it mid-swap
        try:
            with open(MANIFEST, newline="", encoding="utf-8") as f:
                return list(csv.DictReader(f))
        except OSError:
            time.sleep(0.2)
    return []


def status_summary():
    rows = read_manifest()
    count = collections.Counter(r.get("status", "") for r in rows)
    archived = sum(1 for r in rows if r.get("archived_at"))
    uploaded = count.get("uploaded", 0)
    new_dir = BASE / "new"
    waiting = len(list(new_dir.glob("*.mp4"))) if new_dir.exists() else 0
    clips = [{"file": r.get("filename", ""), "date": (r.get("updated") or "")[:10], "status": r.get("status", ""),
              "youtube": r.get("youtube_id", ""), "archived": bool(r.get("archived_at"))}
             for r in rows if r.get("status") in ("uploaded", "fetched", "failed")]
    clips.sort(key=lambda c: c["file"], reverse=True)
    return {"uploaded": uploaded, "archived": archived, "to_archive": max(0, uploaded - archived),
            "waiting_upload": waiting, "failed": count.get("failed", 0), "clips": clips[:60]}


def other_pipeline_running():
    """True when some other clip_pipeline.py upload/run/archive is already running (e.g. started at the PC)."""
    if sys.platform != "win32":
        return False
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'clip_pipeline\\.py\\s+(run|upload|archive)' "
          "-and $_.ProcessId -ne %d } | Measure-Object | ForEach-Object Count" % (STATE["job"]["pid"] if STATE["job"] and STATE["job"]["proc"].poll() is None else 0))
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=30, creationflags=NO_WINDOW).stdout.strip()
        return out.isdigit() and int(out) > 0
    except (OSError, subprocess.SubprocessError):
        return True                         # if we cannot tell, assume busy: the safe answer


def pipeline_cmd(action, extra=()):
    return [sys.executable, "-B", str(PIPELINE), action, "--yes", *extra]


def dry_run(action):
    r = subprocess.run(pipeline_cmd(action, ["--dry-run"]), cwd=BASE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    return (r.stdout + r.stderr).strip()


def job_view():
    j = STATE["job"]
    if not j:
        return None
    rc = j["proc"].poll()
    return {"action": j["action"], "running": rc is None, "exit": rc, "started": j["started"],
            "output": "".join(list(j["lines"])[-60:])}


def start_job(action):
    proc = subprocess.Popen(pipeline_cmd(action), cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1,
                            creationflags=NO_WINDOW)
    job = {"action": action, "proc": proc, "pid": proc.pid, "started": time.strftime("%H:%M:%S"),
           "lines": collections.deque(maxlen=400)}

    def pump():
        for line in proc.stdout:
            job["lines"].append(line.replace("\r", "\n") if "\r" in line and "\n" not in line else line)
    threading.Thread(target=pump, daemon=True).start()
    STATE["job"] = job


# --------------------------------------------------------------------------- page

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><meta name="robots" content="noindex">
<title>Contact Sheet</title>
<style>
:root{color-scheme:dark;--bg:#050506;--panel:#0d0d10;--edge:#2a0a12;--crim:#8c0f26;--crimhi:#c4162f;--text:#e6e1e2;--dim:#8a7f82}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.45 system-ui,Segoe UI,sans-serif;padding:16px;max-width:760px;margin-inline:auto}
h1{font-size:1.2rem;margin:.2rem 0 .1rem;letter-spacing:.04em}
.sub{color:var(--dim);font-size:.85rem;margin-bottom:14px}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--edge);border-radius:8px;padding:10px 12px}
.card b{display:block;font-size:1.5rem}.card span{color:var(--dim);font-size:.8rem}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
button{background:var(--panel);color:var(--text);border:1px solid var(--crim);border-radius:6px;padding:12px 14px;font:inherit;min-height:44px;flex:1 1 140px}
button:hover:not(:disabled),button:focus-visible{background:var(--crim);outline:2px solid var(--crimhi);outline-offset:2px}
button:disabled{opacity:.4}
button.go{background:var(--crim)}
pre{background:var(--panel);border:1px solid var(--edge);border-radius:8px;padding:10px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:13px/1.4 Consolas,monospace;max-height:320px}
.box{background:var(--panel);border:1px solid var(--crimhi);border-radius:8px;padding:12px;margin:12px 0}
.box[hidden]{display:none}
input[type=text]{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--crim);border-radius:6px;padding:12px;font:inherit;text-transform:uppercase}
ul{list-style:none;margin:0;padding:0}li{padding:7px 0;border-bottom:1px solid var(--edge);font-size:.9rem;word-break:break-all}
li small{color:var(--dim)}.ok{color:#7fd18b}.warn{color:#e0a458}.bad{color:#ff6b7a}
.note{color:var(--dim);font-size:.8rem;margin-top:16px}
@media (prefers-reduced-motion:no-preference){*{transition:background .25s}}
</style></head><body>
<h1>CONTACT SHEET</h1>
<div class="sub">Local network only. Uploads are always unlisted. Archive only copies and checks, never deletes.</div>
<div class="cards" id="cards" aria-live="polite"></div>
<div class="row">
<button id="bUp">Preview upload</button>
<button id="bAr">Preview archive</button>
<button id="bRe">Refresh</button></div>
<div class="box" id="confirm" hidden>
<strong id="cTitle"></strong>
<pre id="cText"></pre>
<label for="cWord" id="cLabel"></label>
<input id="cWord" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false">
<div class="row"><button class="go" id="bGo" disabled>Start</button><button id="bNo">Cancel</button></div>
</div>
<div id="jobBox" hidden><h2 style="font-size:1rem">Running job</h2><pre id="job"></pre></div>
<h2 style="font-size:1rem">Clips</h2><ul id="clips"></ul>
<p class="note">Publishing a video (unlisted to public) is deliberately not available here. Do that at the PC.</p>
<script>
"use strict";
const $ = id => document.getElementById(id);
let plan = null;
async function api(name, body) {
  const r = await fetch("api/" + name, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
  const j = await r.json().catch(() => ({error: "Bad reply (" + r.status + ")"}));
  if (!r.ok) j.error = j.error || ("Error " + r.status);
  return j;
}
function card(n, label) { const d = document.createElement("div"); d.className = "card"; const b = document.createElement("b"); b.textContent = n; const s = document.createElement("span"); s.textContent = label; d.append(b, s); return d; }
async function refresh() {
  const s = await api("status");
  if (s.error) { $("cards").textContent = s.error; return; }
  $("cards").replaceChildren(card(s.uploaded, "on YouTube (unlisted)"), card(s.archived, "archived to Drive"),
    card(s.to_archive, "waiting to archive"), card(s.waiting_upload, "waiting to upload"));
  const ul = $("clips"); ul.replaceChildren();
  for (const c of s.clips) {
    const li = document.createElement("li");
    li.textContent = c.file + "  ";
    const st = document.createElement("small");
    st.className = c.status === "failed" ? "bad" : (c.archived ? "ok" : "warn");
    st.textContent = c.status === "uploaded" ? (c.archived ? "uploaded, archived" : "uploaded, not archived yet") : c.status;
    li.append(st); ul.append(li);
  }
  const j = s.job;
  $("jobBox").hidden = !j;
  if (j) { $("job").textContent = (j.running ? "RUNNING " : "FINISHED (exit " + j.exit + ") ") + j.action + " since " + j.started + "\n\n" + j.output; }
  $("bUp").disabled = $("bAr").disabled = !!(j && j.running);
}
async function preview(action) {
  $("confirm").hidden = false; $("cTitle").textContent = "Checking..."; $("cText").textContent = "";
  $("cWord").value = ""; $("bGo").disabled = true; plan = null;
  const p = await api("plan", {action});
  if (p.error) { $("cTitle").textContent = "Cannot start"; $("cText").textContent = p.error; return; }
  plan = p;
  $("cTitle").textContent = action === "upload" ? "This will upload as UNLISTED:" : "This will copy to Google Drive and check:";
  $("cText").textContent = p.text;
  $("cLabel").textContent = "Type " + p.word + " to confirm";
  $("cWord").focus();
}
$("bUp").onclick = () => preview("upload");
$("bAr").onclick = () => preview("archive");
$("bRe").onclick = refresh;
$("bNo").onclick = () => { $("confirm").hidden = true; plan = null; };
$("cWord").oninput = () => { $("bGo").disabled = !plan || $("cWord").value.trim().toUpperCase() !== plan.word; };
$("bGo").onclick = async () => {
  if (!plan) return;
  $("bGo").disabled = true;
  const r = await api("run", {action: plan.action, nonce: plan.nonce, word: $("cWord").value.trim().toUpperCase()});
  if (r.error) { $("cTitle").textContent = "Not started"; $("cText").textContent = r.error; plan = null; return; }
  $("confirm").hidden = true; plan = null; refresh();
};
refresh(); setInterval(refresh, 5000);
</script></body></html>
"""

# --------------------------------------------------------------------------- server


class Handler(BaseHTTPRequestHandler):
    server_version = "ContactSheetLAN"
    sys_version = ""

    def log_message(self, *a):               # the token is in the URL: keep it out of any log
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-transform")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                         "style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _route(self):
        """Return the path after the token, or None (and send 404) when anything about the request is wrong."""
        if self.headers.get("Host", "") != STATE["host"]:        # also blocks DNS-rebinding tricks
            self._json(404, {"error": "not found"})
            return None
        parts = self.path.split("?")[0].split("/")
        tok = parts[1] if len(parts) > 1 else ""
        if STATE["bad"] >= 30 or not hmac.compare_digest(tok.encode(), STATE["token"].encode()):
            STATE["bad"] += 1
            self._json(404, {"error": "not found"})
            return None
        return "/".join(parts[2:])

    def do_GET(self):
        rest = self._route()
        if rest is None:
            return
        if rest == "":
            self._send(200, PAGE, "text/html")
        elif rest == "api/status":
            s = status_summary()
            s["job"] = job_view()
            self._json(200, s)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        rest = self._route()
        if rest is None:
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
        except (ValueError, OSError):
            return self._json(400, {"error": "bad request"})
        action = body.get("action")
        if action not in ACTIONS:
            return self._json(400, {"error": "unknown action"})
        with STATE["lock"]:
            running = STATE["job"] and STATE["job"]["proc"].poll() is None
            if running:
                return self._json(409, {"error": "A job is already running. Wait for it to finish."})
            if rest == "api/plan":
                if other_pipeline_running():
                    return self._json(409, {"error": "The pipeline is already running at the PC (an upload or archive). "
                                                     "Wait for it to finish, then try again."})
                text = dry_run(action)
                nonce = secrets.token_urlsafe(16)
                STATE["plans"] = {nonce: {"action": action, "text": text, "t": time.time()}}   # only the latest plan is valid
                return self._json(200, {"action": action, "word": ACTIONS[action], "nonce": nonce, "text": text})
            if rest == "api/run":
                plan = STATE["plans"].pop(str(body.get("nonce", "")), None)       # single use
                if not plan or plan["action"] != action or time.time() - plan["t"] > 300:
                    return self._json(400, {"error": "That preview has expired. Press Preview again."})
                if str(body.get("word", "")).strip().upper() != ACTIONS[action]:
                    return self._json(400, {"error": "The confirmation word did not match."})
                if other_pipeline_running():
                    return self._json(409, {"error": "The pipeline is already running at the PC."})
                if dry_run(action) != plan["text"]:
                    return self._json(409, {"error": "Things changed since the preview. Press Preview again."})
                start_job(action)
                return self._json(200, {"started": action})
        self._json(404, {"error": "not found"})


class Server(ThreadingHTTPServer):
    allow_reuse_address = False             # on Windows this flag lets a second program share the port


def main():
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description="Contact Sheet LAN page")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--hours", type=float, default=4.0, help="stop by itself after this many hours")
    ap.add_argument("--host", help="private LAN address to listen on (default: detected)")
    args = ap.parse_args()

    ip = args.host or lan_ip()
    try:
        ok = ip and ipaddress.ip_address(ip).is_private and not ipaddress.ip_address(ip).is_loopback
    except ValueError:
        ok = False
    if not ok:
        raise SystemExit("No private LAN address found (are you on your home network?). Not starting.")
    if not PIPELINE.exists():
        raise SystemExit("clip_pipeline.py not found next to clip_web.py.")

    STATE["token"] = secrets.token_urlsafe(24)
    STATE["host"] = f"{ip}:{args.port}"
    srv = Server((ip, args.port), Handler)
    threading.Timer(args.hours * 3600, srv.shutdown).start()
    print("\nContact Sheet LAN page is running (home network only).\n")
    print(f"  Open this on your phone (same Wi-Fi):\n\n    http://{STATE['host']}/{STATE['token']}/\n")
    print(f"  It stops by itself after {args.hours:g} h. Press Ctrl+C to stop sooner.")
    print("  Do not share the link. The token changes every time this starts.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        print("Stopped.")


if __name__ == "__main__":
    main()
