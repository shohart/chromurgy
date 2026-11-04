#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Export one revision of an Assembla SVN path over plain HTTP (the svn client
hangs on that server): fetch_svn.py URL_BASE REV PATH OUT_DIR, e.g.
fetch_svn.py https://subversion.assembla.com/svn/chdkptp 1535 trunk build/chdkptp-src
Anonymous access is guest/guest."""
import base64
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

base, rev, path, out = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3].strip("/"), Path(sys.argv[4])
auth = "Basic " + base64.b64encode(b"guest:guest").decode()


def get(rel: str) -> bytes:
    req = urllib.request.Request(f"{base}/!svn/bc/{rev}/{path}/{rel}", headers={"Authorization": auth})
    for attempt in range(8):                 # the server drops connections under load: retry with backoff
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404):
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"giving up on {rel}")


def walk(rel: str = "") -> list[str]:
    html = get(rel).decode("utf-8", "replace")
    files = []
    for href in re.findall(r'<li><a href="([^"]+)">', html):
        if href == "../":
            continue
        if href.endswith("/"):
            files += walk(rel + href)
        else:
            files.append(rel + href)
    return files


files = walk()
out.mkdir(parents=True, exist_ok=True)


def fetch(rel: str) -> None:
    p = out / urllib.request.url2pathname(rel)
    if p.exists():                            # resume an interrupted export
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(get(rel))


with ThreadPoolExecutor(3) as ex:
    list(ex.map(fetch, files))
print(f"{len(files)} files from {path}@{rev} into {out}")
