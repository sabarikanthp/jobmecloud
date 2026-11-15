"""Keep a tailored resume to the same page count as the original."""

import io
import math
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass

from jobmecloud.applydocs.content import TailoredBullet, TailoredContent, TailoredRole

PageCounter = Callable[[bytes], int | None]
CHARS_PER_LINE = 90
LINE_SLACK = 2
MAX_WORD_COUNTS = 8
UNCONFIRMED_NOTE = "Couldn't confirm the page count"


def _pages(n: int) -> str:
    return f"{n} page" if n == 1 else f"{n} pages"


def same_pages_note(n: int) -> str:
    return f"{_pages(n)}, same as your resume"


def closest_note(got: int, want: int) -> str:
    return f"{_pages(got)}; your resume has {want}. JobMe kept the closest version."


def original_page_count(data: bytes) -> int | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("docProps/app.xml").decode("utf-8", errors="replace")
    except Exception:
        return None
    m = re.search(r"<Pages>\s*(\d+)\s*</Pages>", xml)
    if not m:
        return None
    n = int(m.group(1))
    return n if n > 0 else None


def unverified_page_counter(data: bytes) -> int | None:
    """JobMeCloud has no Word to count pages with, so the page count is never confirmed."""
    return None


def estimate_lines(text: str) -> int:
    return max(1, math.ceil(len(text) / CHARS_PER_LINE))


@dataclass
class FitResult:
    docx: bytes
    content: TailoredContent
    pages: int | None
    note: str


def _original_text(original: TailoredContent, role: int, source: int) -> str | None:
    for r in original.roles:
        if r.role == role:
            for b in r.bullets:
                if b.source == source:
                    return b.text
    return None


def _total_lines(content: TailoredContent) -> int:
    return sum(estimate_lines(b.text) for r in content.roles for b in r.bullets)


def _drop_one(content: TailoredContent) -> bool:
    """Drop the last bullet of the role with the most bullets; never a role's only bullet."""
    best = None
    for r in content.roles:
        if len(r.bullets) > 1 and (best is None or len(r.bullets) > len(best.bullets)):
            best = r
    if best is None:
        return False
    best.bullets.pop()
    return True


def _estimate_fit(content: TailoredContent, original: TailoredContent) -> None:
    for r in content.roles:
        for b in r.bullets:
            orig = _original_text(original, r.role, b.source)
            if orig is not None and b.text != orig and estimate_lines(b.text) > estimate_lines(orig):
                b.text = orig
    limit = _total_lines(original) + LINE_SLACK
    while _total_lines(content) > limit and _drop_one(content):
        pass


def _left_out(content: TailoredContent, original: TailoredContent) -> list[tuple[int, TailoredBullet]]:
    have = {(r.role, b.source) for r in content.roles for b in r.bullets}
    return [(r.role, b) for r in original.roles for b in r.bullets if (r.role, b.source) not in have]


def _put_back(content: TailoredContent, role: int, bullet: TailoredBullet) -> None:
    for r in content.roles:
        if r.role == role:
            r.bullets.append(bullet.model_copy())
            return
    new = TailoredRole(role=role, bullets=[bullet.model_copy()])
    index = next((i for i, r in enumerate(content.roles) if r.role > role), len(content.roles))
    content.roles.insert(index, new)


def fit_pages(
    render: Callable[[TailoredContent], bytes],
    content: TailoredContent,
    original: TailoredContent,
    target: int | None,
    counter: PageCounter,
) -> FitResult:
    current = content.model_copy(deep=True)

    def estimate_result(c: TailoredContent) -> FitResult:
        _estimate_fit(c, original)
        return FitResult(render(c), c, None, UNCONFIRMED_NOTE)

    if target is None:
        return estimate_result(current)

    counts = 0
    docx = render(current)
    pages = counter(docx)
    counts += 1
    if pages is None:
        return estimate_result(current)
    best = (abs(pages - target), docx, current.model_copy(deep=True), pages)

    def consider(d: bytes, c: TailoredContent, p: int) -> None:
        nonlocal best
        if abs(p - target) <= best[0]:
            best = (abs(p - target), d, c.model_copy(deep=True), p)

    while pages > target and counts < MAX_WORD_COUNTS and _drop_one(current):
        docx = render(current)
        pages = counter(docx)
        counts += 1
        if pages is None:
            return estimate_result(current)
        consider(docx, current, pages)

    if pages < target:
        for role, bullet in _left_out(current, original):
            if pages >= target or counts >= MAX_WORD_COUNTS:
                break
            trial = current.model_copy(deep=True)
            _put_back(trial, role, bullet)
            trial_docx = render(trial)
            trial_pages = counter(trial_docx)
            counts += 1
            if trial_pages is None:
                return estimate_result(trial)
            if trial_pages > target:
                break
            current, docx, pages = trial, trial_docx, trial_pages
            consider(docx, current, pages)

    _, docx, final, got = best
    note = same_pages_note(target) if got == target else closest_note(got, target)
    return FitResult(docx, final, got, note)
