"""
relay.py - tiny local web server for Pseudo-ATC. Python 3 standard library only, nothing to install.

What it does
  1. Serves the Pseudo-ATC page at http://localhost:8080
  2. Fetches real METARs for the page (aviationweather.gov, then NOAA tgftp as a backup)
     at http://localhost:8080/metar/KSJC
Because the page and the weather both come from this one server, the browser has nothing to block,
so "Real METAR from the internet" and "Test METAR fetch" in the page work.

How to run
  python relay.py            (uses port 8080)
  python relay.py 9000       (uses another port)

Where it finds the page, in this order
  - pseudo_atc.html or index.html in the same folder as this script
  - otherwise it downloads it from your GitHub page (PAGE_URLS below)

Open the address it prints. On the same Wi-Fi, other devices can use the "network" address it prints.
Press Ctrl+C (or stop the script in your app) to quit.
"""
import os
import re
import socket
import sys
import time
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8080
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
LOCAL_NAMES = ["pseudo_atc.html", "index.html"]
PAGE_URLS = ["https://josephL56.github.io/", "https://josephL56.github.io/pseudo_atc.html"]
PAGE_MARKER = "Pseudo-ATC"          # a downloaded page must contain this, so a plain README page is not mistaken for the app
CACHE_S = 60                        # reuse a fetched METAR for this long
TIMEOUT_S = 10
HEADERS = {"User-Agent": "pseudo-atc-relay/1.0 (personal flight sim project)"}
ICAO_RE = re.compile(r"^[A-Za-z0-9]{4}$")
METAR_RE = re.compile(r'\b(?:METAR |SPECI )?[A-Z0-9]{4} \d{6}Z [^"\n<\\]+')

_cache = {}                         # ICAO -> (time, raw, source)
_lock = threading.Lock()
_page = {"html": None, "src": None}


def http_get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return None, "HTTP %s" % e.code
    except urllib.error.URLError as e:
        return None, "could not connect (%s)" % (e.reason,)
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def get_metar(icao):
    """Return (raw, source, None) or (None, None, why)."""
    icao = icao.upper()
    with _lock:
        hit = _cache.get(icao)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1], hit[2] + " (cached)", None
    why = []
    sources = [
        ("aviationweather.gov", "https://aviationweather.gov/api/data/metar?ids=%s&format=raw" % icao),
        ("NOAA tgftp", "https://tgftp.nws.noaa.gov/data/observations/metar/stations/%s.TXT" % icao),
    ]
    for name, url in sources:
        text, err = http_get(url)
        if err:
            why.append("%s: %s" % (name, err))
            continue
        m = METAR_RE.search(text or "")
        if m:
            raw = m.group(0).strip()
            with _lock:
                _cache[icao] = (time.time(), raw, name)
            return raw, name, None
        why.append("%s: no METAR in the reply" % name)
    return None, None, "; ".join(why)


# The page only asks the relay if it has a source for it. Newer pages already do; this adds it to older copies.
RELAY_SOURCE = 'l.push({ name: "relay", url: icao => "/metar/" + icao });\n    '
ANCHOR = 'l.push({ name: "aviationweather.gov"'


def patch_page(html):
    if '"/metar/"' not in html and ANCHOR in html:
        html = html.replace(ANCHOR, RELAY_SOURCE + ANCHOR, 1)
    return html


def load_page():
    for name in LOCAL_NAMES:
        path = os.path.join(HERE, name)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                html = f.read()
            if PAGE_MARKER in html:
                return patch_page(html), "file " + name
    for url in PAGE_URLS:
        html, err = http_get(url)
        if html and PAGE_MARKER in html:
            return patch_page(html), url
    return None, None


class Handler(BaseHTTPRequestHandler):
    server_version = "PseudoATCRelay/1.0"

    def log_message(self, fmt, *args):
        sys.stdout.write("  %s %s\n" % (self.address_string(), fmt % args))

    def send(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")   # lets a page hosted elsewhere (e.g. GitHub) call this relay too
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html", "/pseudo_atc.html"):
            if _page["html"] is None:
                _page["html"], _page["src"] = load_page()
            if _page["html"] is None:
                self.send(404, "Could not find the Pseudo-ATC page. Put pseudo_atc.html in the same folder as relay.py, "
                               "or check the PAGE_URLS at the top of relay.py and your internet connection.")
                return
            self.send(200, _page["html"], "text/html; charset=utf-8")
            return
        m = re.match(r"^/metar/([^/]+)$", path)
        if m:
            icao = m.group(1)
            if not ICAO_RE.match(icao):          # only 4-character airport codes, nothing else is ever fetched
                self.send(400, "bad airport code")
                return
            raw, src, why = get_metar(icao)
            if raw:
                self.send(200, raw + "\n")
            else:
                self.send(502, "no METAR for %s (%s)" % (icao.upper(), why))
            return
        if path == "/status":
            self.send(200, "relay ok; page from %s; %d METARs cached\n" % (_page["src"] or "not loaded yet", len(_cache)))
            return
        self.send(404, "not found")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))     # no packet is sent; this just picks the local network address
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


def main():
    html, src = load_page()
    _page["html"], _page["src"] = html, src
    print("Pseudo-ATC relay")
    print("  page: %s" % (("loaded from " + src) if html else "NOT FOUND (put pseudo_atc.html next to this script)"))
    test, how, why = get_metar("KSFO")
    print("  weather: %s" % (("OK via %s (KSFO: %s)" % (how, test)) if test else "could not fetch a test METAR (" + str(why) + ")"))
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError as e:
        print("\nCould not start on port %d (%s). Try another: python relay.py 9000" % (PORT, e))
        return
    ip = lan_ip()
    print("\nOpen this on THIS device:       http://localhost:%d" % PORT)
    if ip:
        print("Open this from another device:  http://%s:%d   (same Wi-Fi)" % (ip, PORT))
    print("\nLeave this running. Press Ctrl+C to stop.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


main()
