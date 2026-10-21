"""
fetch_metar.py - fetch the current METAR for the Pseudo-ATC California demo airports and print them.

Only the Python standard library is used, so it runs as-is in an online Python compiler.
Paste the whole file in, press Run, and read the report at the bottom.

It tries two public sources and tells you exactly what happened with each:
  1. aviationweather.gov  (one request for all airports)
  2. NOAA tgftp text files (one request per airport) - used for any airport source 1 did not return
"""
import json
import re
import time
import urllib.request
import urllib.error

# The 18 airports in the demo (same list as the page's California scenery).
AIRPORTS = {
    "KSJC": "San Jose Intl", "KSFO": "San Francisco Intl", "KOAK": "Oakland Intl",
    "KSQL": "San Carlos", "KPAO": "Palo Alto", "KRHV": "Reid-Hillview",
    "KMRY": "Monterey Regional", "KSNS": "Salinas Municipal", "KSBP": "San Luis Obispo",
    "KSMX": "Santa Maria", "KSBA": "Santa Barbara", "KOXR": "Oxnard",
    "KVNY": "Van Nuys", "KBUR": "Burbank", "KLAX": "Los Angeles Intl",
    "KLGB": "Long Beach", "KSNA": "John Wayne Orange County", "KSMO": "Santa Monica",
}
TIMEOUT_S = 10
HEADERS = {"User-Agent": "pseudo-atc-demo/1.0 (personal flight sim project)"}


def get(url):
    """Return (text, None) on success or (None, reason) on failure."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return None, "HTTP %s %s" % (e.code, e.reason)
    except urllib.error.URLError as e:
        return None, "could not connect (%s)" % (e.reason,)
    except Exception as e:  # timeouts, sandbox restrictions, anything else
        return None, "%s: %s" % (type(e).__name__, e)


def extract_metar(text):
    """Pull a raw METAR line out of JSON or plain text."""
    m = re.search(r'\b(?:METAR |SPECI )?[A-Z]{4} \d{6}Z [^"\n<\\]+', text)
    return m.group(0).strip() if m else None


def from_aviationweather(icaos):
    url = "https://aviationweather.gov/api/data/metar?ids=%s&format=json" % ",".join(icaos)
    text, err = get(url)
    if err:
        return {}, err
    if not text.strip():
        return {}, "empty reply (no METARs for these airports)"
    try:
        rows = json.loads(text)
    except ValueError:
        return {}, "reply was not JSON"
    out = {}
    for row in rows:
        raw = row.get("rawOb") or ""
        icao = row.get("icaoId") or (raw.split()[1] if raw.startswith("METAR") else raw.split()[0] if raw else "")
        if icao and raw:
            out[icao] = raw.strip()
    return out, None


def from_noaa_text(icao):
    url = "https://tgftp.nws.noaa.gov/data/observations/metar/stations/%s.TXT" % icao
    text, err = get(url)
    if err:
        return None, err
    raw = extract_metar(text)
    return (raw, None) if raw else (None, "no METAR in the reply")


def decode(raw):
    """Small decoder: wind, visibility, ceiling, QNH. Same idea as the page's parser."""
    t = " " + re.sub(r"\s+RMK\b.*$", "", raw.upper()) + " "
    d = {}
    m = re.search(r" (VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?(KT|MPS) ", t)
    if m:
        k = 1.94384 if m.group(4) == "MPS" else 1
        spd = round(int(m.group(2)) * k)
        gust = round(int(m.group(3)) * k) if m.group(3) else None
        d["wind"] = "calm" if spd == 0 else "%s at %d kt%s" % ("variable" if m.group(1) == "VRB" else m.group(1) + " deg", spd, " gusting %d" % gust if gust else "")
    if " CAVOK " in t:
        d["vis"] = "10 km+"
    else:
        m = re.search(r" (\d{4}) ", t)
        if m and not re.search(r" \d{6}Z ", m.group(0)):
            d["vis"] = "10 km+" if m.group(1) == "9999" else "%d m" % int(m.group(1))
        else:
            m = re.search(r" (M?\d+(?: \d/\d)?|\d/\d)SM ", t)
            if m:
                d["vis"] = m.group(1) + " SM"
    lay = [int(x) * 100 for x in re.findall(r" (?:BKN|OVC|VV)(\d{3})", t)]
    d["ceiling"] = "%d ft" % min(lay) if lay else "none"
    if re.search(r" (?:\+|-)?(?:VC)?TS\w* ", t):
        d["storm"] = "thunderstorm"
    m = re.search(r" Q(\d{4}) ", t)
    if m:
        d["qnh"] = "%s hPa" % m.group(1)
    else:
        m = re.search(r" A(\d{4}) ", t)
        if m:
            d["qnh"] = "%.2f inHg" % (int(m.group(1)) / 100.0)
    return d


def main():
    icaos = list(AIRPORTS)
    started = time.time()
    print("Fetching METARs for %d California demo airports...\n" % len(icaos))

    found, err1 = from_aviationweather(icaos)
    src = {i: "aviationweather.gov" for i in found}
    print("Source 1, aviationweather.gov: %s" % ("OK, %d of %d airports" % (len(found), len(icaos)) if not err1 else "FAILED - " + err1))

    noaa_errs = {}
    missing = [i for i in icaos if i not in found]
    if missing:
        ok = 0
        for icao in missing:
            raw, err = from_noaa_text(icao)
            if raw:
                found[icao] = raw
                src[icao] = "NOAA tgftp"
                ok += 1
            else:
                noaa_errs[icao] = err
                if len(noaa_errs) >= 3 and ok == 0:      # clearly blocked, do not wait for every airport
                    break
        tried = ok + len(noaa_errs)
        if ok:
            print("Source 2, NOAA tgftp: OK, %d of %d tried" % (ok, tried))
        else:
            print("Source 2, NOAA tgftp: FAILED - %s" % next(iter(noaa_errs.values()), "not tried"))

    print("\n" + "=" * 72)
    for icao in icaos:
        if icao in found:
            d = decode(found[icao])
            print("%s  %s  [%s]" % (icao, AIRPORTS[icao], src[icao]))
            print("   %s" % found[icao])
            print("   wind %s | vis %s | ceiling %s | QNH %s%s" % (
                d.get("wind", "?"), d.get("vis", "?"), d.get("ceiling", "?"), d.get("qnh", "?"),
                " | " + d["storm"] if "storm" in d else ""))
        else:
            print("%s  %s  - no METAR" % (icao, AIRPORTS[icao]))
    print("=" * 72)
    print("Got %d of %d airports in %.1f s." % (len(found), len(icaos), time.time() - started))

    if found:
        # Clean block for the Pseudo ATC page: copy everything between the two marker lines,
        # paste it into the "Real weather for the demo" box on the Demo tab, then press Load.
        print("\n----- COPY FROM HERE (paste into Pseudo ATC, Demo tab) -----")
        for icao in icaos:
            if icao in found:
                print(found[icao] if found[icao].startswith(("METAR", "SPECI")) else "METAR " + found[icao])
        print("----- COPY TO HERE -----")

    if not found:
        print("\nNothing came back. Most likely this online compiler blocks outbound internet,")
        print("or it only lets approved sites through. Try another online compiler, or tell me")
        print("the exact error lines printed above for Source 1 and Source 2.")
    elif len(found) < len(icaos):
        print("\nSome airports have no recent METAR. That is normal for the small fields.")


main()
