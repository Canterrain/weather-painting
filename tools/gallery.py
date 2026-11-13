#!/usr/bin/env python3
"""The gallery's GitHub workflow (.github/workflows/gallery.yml).

    python3 tools/gallery.py check     a submission was opened or edited
    python3 tools/gallery.py approve   the owner labeled it "approved"
    python3 tools/gallery.py withdraw  it was closed without approval
    python3 tools/gallery.py prune     docs/gallery.json changed: delete the
                                       releases of paintings taken out of it

Reads the issue from the event GitHub hands the workflow, and uses the gh
command line with the workflow's token. Nothing from the issue is ever run or
passed through a shell: the zip is unpacked and checked by painter/submission.py.

A submission's preview goes up as a pre-release, submission-<issue>, so it
can be shown on the issue. Approval publishes the painting as a release,
gallery-<name>, and adds it to docs/gallery.json, the list the frames'
settings page shows.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / "docs" / "gallery.json"
WORK = ROOT / "out" / "gallery"
MAX_ZIP = 30 * 1024 * 1024
ATTACHMENT = re.compile(r"https://github\.com/user-attachments/files/\d+/[^\s)\]\"'<>]+\.zip", re.I)
FIELDS = {"Painting's name": "title", "Artist's name": "artist", "License": "license"}
LICENSES = {"CC BY-NC-ND 4.0", "CC BY-NC 4.0", "CC BY 4.0"}


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=check, text=True, capture_output=True)


def comment(issue: int, body: str) -> None:
    gh("issue", "comment", str(issue), "--body", body)


def fields(body: str) -> dict:
    """The answers in an issue form's body: '### Question\\n\\nanswer' blocks."""
    out = {}
    for block in re.split(r"^### ", body or "", flags=re.M)[1:]:
        question, _, answer = block.partition("\n")
        key = FIELDS.get(question.strip())
        if key:
            out[key] = answer.strip()
    lic = out.get("license", "")
    out["license"] = next((l for l in LICENSES if lic.startswith(l)), "")
    return out


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "painting"


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "weather-painting-gallery"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as out:
        got = 0
        while chunk := r.read(1 << 16):
            got += len(chunk)
            if got > MAX_ZIP:
                raise ValueError("too large")
            out.write(chunk)


def run_check(issue: dict) -> tuple[bool, dict, Path]:
    """Download and check the submission. Returns (usable, form fields, output folder)."""
    n = issue["number"]
    info = fields(issue.get("body") or "")
    out = WORK / str(n)
    out.mkdir(parents=True, exist_ok=True)
    missing = [q for q, k in FIELDS.items() if not info.get(k)]
    links = ATTACHMENT.findall(issue.get("body") or "")
    if missing or not links:
        need = [f"**{q}**" for q in missing] + ([] if links else ["a **zip** of your layers"])
        comment(n, "### Painting check\n\n❌ The form is missing " + ", ".join(need) +
                ". Edit the issue to add it, and the check runs again.")
        return False, info, out
    try:
        download(links[-1], out / "layers.zip")   # the newest attachment, if there are several
    except Exception:
        comment(n, "### Painting check\n\n❌ The zip couldn't be downloaded, or it's over 30 MB. "
                "Edit the issue to attach it again.")
        return False, info, out
    r = subprocess.run([sys.executable, "-m", "painter.submission", str(out / "layers.zip"),
                        "--out", str(out / "check")], cwd=ROOT, text=True, capture_output=True)
    print(r.stdout, r.stderr)
    report = out / "check" / "report.md"
    if not report.exists():
        comment(n, "### Painting check\n\n❌ Something went wrong checking this painting. The project will take a look.")
        return False, info, out
    return r.returncode == 0, info, out


def check(event: dict) -> None:
    issue = event["issue"]
    n = issue["number"]
    usable, info, out = run_check(issue)
    report = out / "check" / "report.md"
    if not report.exists():
        return
    body = report.read_text()
    if usable:
        tag = f"submission-{n}"
        files = [str(out / "check" / "release" / f) for f in ("cover.jpg", "preview.jpg")]
        if gh("release", "view", tag, check=False).returncode == 0:
            gh("release", "upload", tag, *files, "--clobber")
        else:
            gh("release", "create", tag, *files, "--prerelease", "--title", f"Submission #{n} (not approved)",
               "--notes", f"Preview for #{n}. Not in the gallery unless it's approved.")
        repo = os.environ["GITHUB_REPOSITORY"]
        base = f"https://github.com/{repo}/releases/download/{tag}"
        body += (f"\n![How it looks on the frame]({base}/preview.jpg?v={issue['updated_at']})\n\n"
                 "This is how it looks on the frame's panel in several kinds of weather. "
                 "The project reviews every submission before it joins the gallery.\n")
    comment(n, body)


def approve(event: dict) -> None:
    issue = event["issue"]
    n = issue["number"]
    usable, info, out = run_check(issue)
    if not usable:
        comment(n, "Couldn't approve: the painting doesn't pass the check (see above).")
        return
    tag = f"gallery-{slug(info['title'])}"
    taken = {r["tagName"] for r in json.loads(gh("release", "list", "--limit", "500", "--json", "tagName").stdout)}
    if tag in taken:
        tag = f"{tag}-{n}"
    release = out / "check" / "release"
    gh("release", "create", tag, *sorted(str(p) for p in release.iterdir()),
       "--title", f"{info['title']} by {info['artist']}",
       "--notes", f"A painting for the Weather Painting gallery, from #{n}.\n\n"
                  f"© {info['artist']}, licensed {info['license']}.")
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://github.com/{repo}/releases/download/{tag}/"
    gallery = json.loads(GALLERY.read_text()) if GALLERY.exists() else {"paintings": []}
    gallery["paintings"] = [p for p in gallery["paintings"] if p.get("issue") != n]
    gallery["paintings"].append({"title": info["title"], "artist": info["artist"], "license": info["license"],
                                 "url": url, "cover": url + "cover.jpg", "issue": n})
    GALLERY.write_text(json.dumps(gallery, indent=2, ensure_ascii=False) + "\n")
    subprocess.run(["git", "add", str(GALLERY)], cwd=ROOT, check=True)
    subprocess.run(["git", "-c", "user.name=github-actions[bot]",
                    "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                    "commit", "-m", f"Add \"{info['title']}\" by {info['artist']} to the gallery"], cwd=ROOT, check=True)
    subprocess.run(["git", "push"], cwd=ROOT, check=True)
    gh("release", "delete", f"submission-{n}", "--yes", "--cleanup-tag", check=False)
    comment(n, f"🎨 **{info['title']}** is in the gallery. Frames can choose it from **Painting → From the gallery** "
               "on their settings page, starting in a few minutes. Thank you!")
    gh("issue", "close", str(n), "--reason", "completed")


def withdraw(event: dict) -> None:
    gh("release", "delete", f"submission-{event['issue']['number']}", "--yes", "--cleanup-tag", check=False)


def prune(event: dict) -> None:
    listed = {p["url"] for p in json.loads(GALLERY.read_text())["paintings"]} if GALLERY.exists() else set()
    repo = os.environ["GITHUB_REPOSITORY"]
    for r in json.loads(gh("release", "list", "--limit", "500", "--json", "tagName").stdout):
        tag = r["tagName"]
        if tag.startswith("gallery-") and f"https://github.com/{repo}/releases/download/{tag}/" not in listed:
            print(f"deleting {tag}, which isn't in the gallery any more")
            gh("release", "delete", tag, "--yes", "--cleanup-tag")


def main() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    {"check": check, "approve": approve, "withdraw": withdraw, "prune": prune}[sys.argv[1]](event)


if __name__ == "__main__":
    main()
