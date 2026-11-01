#!/usr/bin/env python3
"""
brain-check: a deterministic auditor for a markdown "second brain".

Agents write into the brain. This tool decides what agents are allowed to read back.

Every note carries a small frontmatter block:
    status: checked | unverified
    source: where the claim came from (file, meeting, ticket, url)
    written_by: human | <agent name>
    expires: YYYY-MM-DD (optional)
    facts: key=value; key=value   (optional, used for contradiction checks)

Checks (no LLM involved, every rule is plain code):
  1. routing drift      folders on disk vs the routing table in agents.md
  2. map bloat          agents.md over 200 lines
  3. broken links       [[note]] pointing at nothing
  4. contradictions     two notes asserting different values for the same fact
  5. expiry             notes past their expiry date
  6. unsourced claims   agent-written notes with no source
  7. protected writes   agent writes inside read-only folders
  8. sycophancy guard   agents.md missing the "push back" rule

Output: a report, plus trusted_context.md built ONLY from notes that pass.
"""
import re
import sys
from datetime import date
from pathlib import Path

PROTECTED = {"strategy", "finance"}          # agents may read, never write
MAP_LIMIT = 200
GUARD_PATTERN = re.compile(r"conflicts? with .*(say so|flag|push back)", re.I)

FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
ROUTE_RE = re.compile(r"^\|\s*`?([\w\-/]+)/?`?\s*\|", re.M)


def parse_note(path):
    text = path.read_text()
    meta, body = {}, text
    m = FM_RE.match(text)
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    facts = {}
    for pair in meta.get("facts", "").split(";"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            facts[k.strip()] = v.strip()
    return {"path": path, "meta": meta, "body": body, "facts": facts,
            "links": LINK_RE.findall(body)}


def audit(root: Path, today: date):
    findings = []          # (severity, check, file, message)
    agents_md = root / "agents.md"
    map_text = agents_md.read_text() if agents_md.exists() else ""

    # 1. routing drift
    routed = {r.strip("/").split("/")[0] for r in ROUTE_RE.findall(map_text)
              if r.lower() not in {"folder", "path"} and not set(r) <= {"-"}}
    on_disk = {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    for f in sorted(on_disk - routed):
        findings.append(("WARN", "routing", f + "/", "folder exists but agents.md never routes to it"))
    for f in sorted(routed - on_disk):
        findings.append(("FAIL", "routing", f + "/", "agents.md routes here but the folder is gone"))

    # 2. map bloat
    n = len(map_text.splitlines())
    if n > MAP_LIMIT:
        findings.append(("WARN", "map-size", "agents.md", f"{n} lines, limit is {MAP_LIMIT}"))

    # 8. sycophancy guard
    if not GUARD_PATTERN.search(map_text):
        findings.append(("FAIL", "guard", "agents.md", "no rule telling agents to push back on conflicting requests"))

    notes = [parse_note(p) for p in sorted(root.rglob("*.md")) if p != agents_md
             and not p.name.startswith("_")]
    names = {n["path"].stem for n in notes}
    bad = set()   # notes that cannot enter trusted context

    seen_facts = {}
    for note in notes:
        rel = str(note["path"].relative_to(root))
        meta = note["meta"]
        author = meta.get("written_by", "unknown")

        # 3. broken links
        for link in note["links"]:
            if link not in names:
                findings.append(("WARN", "links", rel, f"[[{link}]] points at nothing"))

        # 5. expiry
        exp = meta.get("expires")
        if exp:
            try:
                if date.fromisoformat(exp) < today:
                    findings.append(("FAIL", "expired", rel, f"expired {exp}"))
                    bad.add(rel)
            except ValueError:
                findings.append(("WARN", "expired", rel, f"unreadable expiry '{exp}'"))

        # 6. unsourced agent claims
        if author != "human" and not meta.get("source"):
            findings.append(("FAIL", "unsourced", rel, f"written by {author} with no source"))
            bad.add(rel)

        # 7. protected writes
        top = note["path"].relative_to(root).parts[0]
        if top in PROTECTED and author != "human":
            findings.append(("FAIL", "protected", rel, f"{author} wrote inside read-only {top}/"))
            bad.add(rel)

        if top not in routed:
            bad.add(rel)   # agents never route here, so it stays out

        if meta.get("status", "unverified") != "checked":
            bad.add(rel)

        # 4. contradictions
        for k, v in note["facts"].items():
            seen_facts.setdefault(k, []).append((v, rel))

    for key, claims in seen_facts.items():
        if len({v for v, _ in claims}) > 1:
            detail = " vs ".join(f"{v} ({r})" for v, r in claims)
            findings.append(("FAIL", "contradiction", key, detail))
            for _, r in claims:
                bad.add(r)

    trusted = [n for n in notes if str(n["path"].relative_to(root)) not in bad]
    return findings, notes, trusted


def write_trusted(root, trusted, today):
    out = [f"# Trusted context ({today.isoformat()})",
           "Built by brain-check. Only notes that are checked, sourced, unexpired,",
           "uncontradicted and written with permission are included.", ""]
    for n in trusted:
        rel = n["path"].relative_to(root)
        out += [f"## {rel}", f"_source: {n['meta'].get('source', 'n/a')}_", n["body"].strip(), ""]
    (root / "_trusted_context.md").write_text("\n".join(out))


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "brain")
    today = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    findings, notes, trusted = audit(root, today)

    order = {"FAIL": 0, "WARN": 1}
    print(f"brain-check  ·  {root}/  ·  {len(notes)} notes  ·  {today}\n")
    for sev, check, where, msg in sorted(findings, key=lambda f: (order[f[0]], f[1])):
        print(f"  {sev}  {check:<13} {where:<32} {msg}")
    fails = sum(1 for f in findings if f[0] == "FAIL")
    warns = len(findings) - fails
    print(f"\n  {fails} fail · {warns} warn")
    print(f"  trusted context: {len(trusted)}/{len(notes)} notes  ->  _trusted_context.md")
    write_trusted(root, trusted, today)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
