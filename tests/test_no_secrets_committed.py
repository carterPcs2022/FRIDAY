"""Guard for a PUBLIC repo: fail if a secret-shaped string or a real .env gets committed.

History: FRIDAY's first commit (2026-06-11) shipped a .env containing an OpenAI
API key. It was untracked the same day but stays readable in the public git
history, so the key had to be revoked. This test exists so it can't happen
again silently.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = {
    "openai/anthropic-style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{30,}"),
    "github token": re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9]{30,})"),
    "groq key": re.compile(r"\bgsk_[A-Za-z0-9]{30,}"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\."),
}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp3", ".wav", ".woff", ".woff2", ".pdf", ".bin", ".zip"}


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        return [ROOT / p for p in out.decode().split("\0") if p]
    except Exception:   # not a git checkout (e.g. a deploy tarball): scan the tree instead
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def test_no_secret_shaped_strings_in_tracked_files():
    hits = []
    for f in tracked_files():
        if not f.is_file() or f.suffix.lower() in SKIP_SUFFIXES or f.stat().st_size > 2_000_000:
            continue
        text = f.read_text(errors="ignore")
        for name, pat in PATTERNS.items():
            if pat.search(text):
                hits.append(f"{f.relative_to(ROOT)} ({name})")
    assert not hits, "secret-shaped strings committed (values not shown): " + ", ".join(hits)


def test_dotenv_is_never_tracked_and_is_gitignored():
    tracked = {p.name for p in tracked_files()}
    assert ".env" not in tracked
    assert re.search(r"^\.env\s*$", (ROOT / ".gitignore").read_text(), re.M)


def test_vulnerable_dependency_versions_cannot_be_selected():
    text = (ROOT / "requirements.txt").read_text()
    floors = {"pypdf": (6, 21, 4), "cryptography": (50, 0, 0)}
    for pkg, floor in floors.items():
        m = re.search(rf"^{pkg}\s*(?:==|>=)\s*([\d.]+)", text, re.M | re.I)
        assert m, f"{pkg} missing"
        assert tuple(int(x) for x in m.group(1).split(".")[:3]) >= floor
