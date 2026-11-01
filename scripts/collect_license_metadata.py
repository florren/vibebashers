"""Сбор version-bound metadata; BSD/MIT legacy notices проверены адресно, по версии."""

import argparse
import email
import hashlib
import importlib.metadata as m
import json
import pathlib
import re
import sys
import tomllib
import zipfile

from licenses_check import license_allowed

parser = argparse.ArgumentParser(
    description="T-152: собрать metadata без установки wheel; версия/hash wheel сверяются с uv.lock"
)
parser.add_argument("--wheel-dir", type=pathlib.Path, required=True)
args = parser.parse_args()
root = pathlib.Path(__file__).resolve().parents[1]
lock = tomllib.loads((root / "backend/uv.lock").read_text())
distributions = {re.sub(r"[-_.]+", "-", d.metadata["Name"]).lower(): d for d in m.distributions()}
rows = []
classes = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
}
aliases = {
    "Apache Software License": "Apache-2.0",
    "PSFL": "PSF-2.0",
    "MIT license": "MIT",
    "MIT License": "MIT",
}
reviewed = {
    ("jinja2", "3.1.6"): (
        "BSD-3-Clause",
        "LICENSE.txt: clauses 1/2/3 read and verified",
    ),
    ("qrcode", "8.2"): (
        "BSD-3-Clause AND MIT",
        "LICENSE: three BSD clauses plus embedded original pyqrnative MIT notice read and verified",
    ),
    ("colorama", "0.4.6"): (
        "BSD-3-Clause",
        "wheel LICENSE.txt: three BSD clauses read and verified",
    ),
}
reviewed_notice_hashes = {
    ("colorama", "0.4.6"): {"cac35c02686e5d04a5a7140bfb3b36e73aed496656e891102e428886d7930318"},
    ("jinja2", "3.1.6"): {"3b49dcee4105eb37bac10faf1be260408fe85d252b8e9df2e0979fc1e094437b"},
    ("qrcode", "8.2"): {"40dfb903c94ee3f789500131311186548ecba5cefd3557623d7700e2522ab994"},
}

for p in lock["package"]:
    n, v = p["name"], p["version"]
    if n == "cx-pulse-backend":
        continue
    d = distributions.get(n)
    license_hashes = {}
    archive = None
    if d and d.version == v:
        md = d.metadata
        for f in d.files or []:
            if ".dist-info/" in str(f) and ("license" in str(f).lower() or "copying" in str(f).lower()):
                license_hashes[str(f)] = hashlib.sha256(d.locate_file(f).read_bytes()).hexdigest()
    else:
        wheel = next(args.wheel_dir.glob(n.replace("-", "_") + "-" + v + "-*.whl"), None)
        if wheel is None:
            raise ValueError(n)
        b = wheel.read_bytes()
        archive = hashlib.sha256(b).hexdigest()
        entry = next(w for w in p["wheels"] if w["url"].endswith("/" + wheel.name))
        assert entry["hash"] == "sha256:" + archive
        with zipfile.ZipFile(wheel) as z:
            md = email.message_from_bytes(z.read(next(f for f in z.namelist() if f.endswith(".dist-info/METADATA"))))
            for f in z.namelist():
                if ".dist-info/" in f and ("license" in f.lower() or "copying" in f.lower()):
                    license_hashes[f] = hashlib.sha256(z.read(f)).hexdigest()
    raw = {k: md.get_all(k, []) for k in ("License-Expression", "License", "Classifier")}
    expr = md.get("License-Expression")
    note = "License-Expression wheel metadata"
    if not expr:
        legacy = md.get("License", "")
        expr = aliases.get(legacy, legacy)
        if not expr or expr == "UNKNOWN" or "\n" in expr:
            expr = " AND ".join(sorted({classes[c] for c in md.get_all("Classifier", []) if c in classes}))
            note = "unambiguous OSI classifier(s); conservative AND"
        if (n, v) in reviewed:
            if set(license_hashes.values()) != reviewed_notice_hashes[(n, v)]:
                raise ValueError(f"legacy notice изменился, нужна повторная проверка: {n} {v}")
            expr, note = reviewed[(n, v)]
    if not license_allowed(expr):
        raise ValueError(f"запрещённая лицензия {n} {v}: {expr}")
    row = {
        "name": n,
        "version": v,
        "expression": expr,
        "metadata": raw,
        "license_files_sha256": license_hashes,
        "source": f"https://pypi.org/project/{n}/{v}/",
        "review": note,
    }
    if archive:
        row["wheel_sha256"] = archive
        row["wheel_url"] = entry["url"]
    rows.append(row)
(root / "docs/licenses/python-metadata.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
sys.stdout.write(f"license metadata: {len(rows)} distributions\n")
