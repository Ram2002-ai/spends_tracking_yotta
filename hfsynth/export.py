"""Exporters (CSV / JSON-Lines / SQL), CSV loader, manifest with checksums, reproducibility check."""
import csv
import dataclasses
import hashlib
import json
import os
import platform
import sys

from . import __version__, schema as S


def fmt_dec(v):
    s = f"{v:.4f}"
    while s.endswith("0") and len(s.split(".")[1]) > 2:
        s = s[:-1]
    return s


def _cell(f, v):
    if v is None:
        return ""
    if f.dtype == "decimal":
        return fmt_dec(v)
    return v


def write_csv(path, table, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(table.cols)
        fs = table.fields
        for r in rows:
            w.writerow([_cell(f, v) for f, v in zip(fs, r)])


def write_jsonl(path, table, rows):
    cols = table.cols
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(dict(zip(cols, r)), separators=(",", ":")) + "\n")


def _sql(f, v):
    if v is None:
        return "NULL"
    if f.dtype == "decimal":
        return fmt_dec(v)
    if f.dtype in ("int", "bool"):
        return str(int(v))
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(path, tables, ds, with_ddl, batch=500):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        if with_ddl:
            fh.write(S.ddl(tables) + "\n")
        fh.write("BEGIN;\n")
        for t in tables:
            rows = ds.get(t.name)
            cols = ", ".join(t.cols)
            for i in range(0, len(rows), batch):
                vals = ",\n".join("(" + ",".join(_sql(f, v) for f, v in zip(t.fields, r)) + ")" for r in rows[i:i + batch])
                fh.write(f"INSERT INTO \"{t.name}\" ({cols}) VALUES\n{vals};\n")
        fh.write("COMMIT;\n")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export(ds, cfg, out, formats=("csv", "json", "sql"), validation=None, evaluation=None, command=""):
    from . import evaluate as E
    dirs = {k: os.path.join(out, k) for k in ("data", "ground_truth", "sql", "docs")}
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    files = {}
    for grp, folder in ((S.TABLES, "data"), (S.GT_TABLES, "ground_truth")):
        for t in grp:
            rows = ds.get(t.name)
            if "csv" in formats:
                p = os.path.join(dirs[folder], t.name + ".csv")
                write_csv(p, t, rows)
                files[p] = len(rows)
            if "json" in formats:
                p = os.path.join(dirs[folder], t.name + ".jsonl")
                write_jsonl(p, t, rows)
                files[p] = len(rows)
    if "sql" in formats:
        p = os.path.join(dirs["sql"], "seed.sql")
        write_sql(p, S.TABLES, ds, True)
        files[p] = sum(len(ds.get(t.name)) for t in S.TABLES)
        p = os.path.join(dirs["sql"], "ground_truth.sql")
        write_sql(p, S.GT_TABLES, ds, True)
        files[p] = sum(len(ds.get(t.name)) for t in S.GT_TABLES)
    docs = {"data_dictionary.md": S.data_dictionary_md(), "schema.sql": S.ddl()}
    if validation is not None:
        docs["validation_summary.md"] = validation.to_md()
        docs["validation_summary.json"] = json.dumps(validation.results, indent=2)
    if evaluation is not None:
        docs["evaluation_summary.md"] = E.to_md(evaluation)
        docs["evaluation_summary.json"] = E.dumps(evaluation)
    for name, text in docs.items():
        p = os.path.join(dirs["docs"], name)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        files[p] = None
    manifest = {
        "generator": "hfsynth", "version": __version__, "seed": cfg.seed,
        "parameters": dataclasses.asdict(cfg), "command": command,
        "python": sys.version.split()[0], "platform": platform.system(),
        "source_manifest": {"external_data": [], "provenance":
                            "100% synthetic. No external or personal data used; all business names are fictional. "
                            "Public references (e.g. MCC codes, US DST rules) used only for schema/logic inspiration."},
        "files": {os.path.relpath(p, out).replace("\\", "/"): {"rows": n, "bytes": os.path.getsize(p), "sha256": _sha(p)}
                  for p, n in sorted(files.items())},
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    return manifest


def load_dataset(out):
    ds = S.Dataset()
    for grp, folder, target in ((S.TABLES, "data", ds.tables), (S.GT_TABLES, "ground_truth", ds.gt)):
        for t in grp:
            rows = []
            with open(os.path.join(out, folder, t.name + ".csv"), newline="", encoding="utf-8") as fh:
                rd = csv.reader(fh)
                header = next(rd)
                assert header == t.cols, f"{t.name}: header mismatch"
                for r in rd:
                    row = []
                    for f, v in zip(t.fields, r):
                        if v == "":
                            row.append(None)
                        elif f.dtype in ("int", "bool"):
                            row.append(int(v))
                        elif f.dtype == "decimal":
                            row.append(float(v))
                        else:
                            row.append(v)
                    rows.append(row)
            target[t.name] = rows
    return ds


def reproducibility(cfg, base, formats, builder):
    """Generate twice with the same seed; compare row counts and SHA-256 of every data file."""
    ms = []
    for i in (1, 2):
        ds, val = builder(cfg)
        ms.append(export(ds, cfg, os.path.join(base, f"run{i}"), formats, val, None, "repro"))
    a, b = ms[0]["files"], ms[1]["files"]
    same = a.keys() == b.keys() and all(a[k]["rows"] == b[k]["rows"] and a[k]["sha256"] == b[k]["sha256"] for k in a)
    lines = ["# Reproducibility report", "", f"Seed {cfg.seed}, users={cfg.users}, txns={cfg.txns}. "
             f"Two independent runs compared: **{'IDENTICAL' if same else 'DIFFERENT'}**", "",
             "| File | Rows run1 | Rows run2 | SHA-256 (run1) | Match |", "|---|---|---|---|---|"]
    for k in sorted(a):
        ok = k in b and a[k] == b[k]
        lines.append(f"| {k} | {a[k]['rows']} | {b.get(k, {}).get('rows')} | `{a[k]['sha256'][:16]}...` | {'yes' if ok else 'NO'} |")
    report = "\n".join(lines) + "\n"
    with open(os.path.join(base, "reproducibility_report.md"), "w", encoding="utf-8") as fh:
        fh.write(report)
    return same, report
