"""Block commits that contain a forbidden word (business name, phone numbers...).

The word list lives OUTSIDE this repository on purpose: a list committed here
would itself leak what it protects. Its path comes from, in order:

1. the environment variable FORBIDDEN_WORDS_FILE
2. the local git setting `privacy.forbiddenWordsFile`
   (git config privacy.forbiddenWordsFile "C:/path/to/forbidden_words.txt")

List format: UTF-8, one entry per line, blank lines and lines starting with
`#` are ignored. Matching ignores case, Hebrew diacritics, invisible bidi
marks and repeated spaces. An entry with 7+ digits is treated as a phone number and also matches
when written with dashes, spaces or a +972 prefix.

The check fails closed: a missing or empty list blocks the commit.
Matches are reported by file, line and entry NUMBER, never by the word itself.

Usage (called by the hooks in .githooks/):
    python tools/check_forbidden_words.py --staged
    python tools/check_forbidden_words.py --message <commit-msg-file>
    python tools/check_forbidden_words.py --all      # every tracked file
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import unicodedata

_BIDI = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff"))
_PHONE_MIN_DIGITS = 7


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).translate(_BIDI)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split()).casefold()


def _phone_variants(digits: str) -> set[str]:
    variants = {digits}
    if digits.startswith("972"):
        variants.add("0" + digits[3:])
    elif digits.startswith("0"):
        variants.add("972" + digits[1:])
    return variants


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def _list_path() -> str | None:
    path = os.environ.get("FORBIDDEN_WORDS_FILE")
    if path:
        return path
    try:
        path = _git("config", "--get", "privacy.forbiddenWordsFile").decode().strip()
    except subprocess.CalledProcessError:
        return None
    return path or None


def load_entries(path: str) -> list[tuple[int, str, set[str]]]:
    """Return (entry number, normalized text, phone digit variants)."""
    entries = []
    with open(path, encoding="utf-8-sig") as f:
        lines = [line.strip() for line in f]
    for raw in lines:
        if not raw or raw.startswith("#"):
            continue
        digits = re.sub(r"\D", "", raw)
        phones = _phone_variants(digits) if len(digits) >= _PHONE_MIN_DIGITS else set()
        entries.append((len(entries) + 1, _normalize(raw), phones))
    return entries


def find_hits(text: str, entries) -> list[tuple[int, int]]:
    """Return (line number, entry number) pairs."""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        norm = _normalize(line)
        digits = re.sub(r"\D", "", line)
        for number, word, phones in entries:
            if word in norm or any(p in digits for p in phones):
                hits.append((lineno, number))
    return hits


def _staged_files() -> list[str]:
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [p for p in out.decode("utf-8").split("\0") if p]


def _tracked_files() -> list[str]:
    return [p for p in _git("ls-files", "-z").decode("utf-8").split("\0") if p]


def _scan_files(paths: list[str], entries, staged: bool) -> list[str]:
    problems = []
    for path in paths:
        for _, number in find_hits(path, entries):
            problems.append(f"  {path} (file name): entry #{number}")
        blob = _git("show", f":{path}") if staged else open(path, "rb").read()
        text = blob.decode("utf-8", errors="ignore")
        for lineno, number in find_hits(text, entries):
            problems.append(f"  {path}:{lineno}: entry #{number}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--all", action="store_true")
    group.add_argument("--message", metavar="FILE")
    args = parser.parse_args()

    path = _list_path()
    if not path or not os.path.isfile(path):
        print("forbidden-words check: list file not found. Set FORBIDDEN_WORDS_FILE or\n"
              "  git config privacy.forbiddenWordsFile <path>   (commit blocked)", file=sys.stderr)
        return 1
    entries = load_entries(path)
    if not entries:
        print("forbidden-words check: the list is empty, fill it first (commit blocked).", file=sys.stderr)
        return 1

    if args.message:
        with open(args.message, encoding="utf-8", errors="ignore") as f:
            problems = [f"  commit message:{ln}: entry #{n}" for ln, n in find_hits(f.read(), entries)]
    elif args.staged:
        problems = _scan_files(_staged_files(), entries, staged=True)
    else:
        problems = _scan_files(_tracked_files(), entries, staged=False)

    if problems:
        print("forbidden-words check: found entries from the forbidden list:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
