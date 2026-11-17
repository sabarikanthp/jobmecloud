"""The code check: plain code that keeps a tailored resume and cover letter truthful.

It enforces numbers (which include years), skills and "Do not claim" terms in the
rewritten text. Named employers and certifications inside prose are left to the
AI self-check; employers, titles, dates and degrees sit in paragraphs that
ApplyDocs never rewrites.
"""

import re

from jobmecloud.applydocs.content import (
    CoverLetter,
    Draft,
    TailoredBullet,
    TailoredContent,
    TailoredRole,
)
from jobmecloud.config.profile import MasterResume, SearchProfile

NUMBER_RE = re.compile(r"\d[\d,.]*%?")
DEFAULT_GREETING = "Dear Hiring Manager,"
DEFAULT_SIGN_OFF = "Sincerely,"
LETTER_LINE_CHARS = 120
HEADLINE_CHARS = 200
HEADLINE_SPLIT_RE = re.compile(r"[|·•–—;,/]|\s-\s")
PHRASE_STRIP = '.,:;!?"\'()[]'


def numbers_in(text: str) -> set[str]:
    return {m.rstrip(".,") for m in NUMBER_RE.findall(text)}


def _banned_term(text: str, terms: list[str]) -> str | None:
    for term in terms:
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE):
            return term
    return None


def _resume_numbers(resume: MasterResume) -> set[str]:
    parts = [resume.summary]
    for role in resume.roles:
        parts += [*role.bullets, role.start, role.end]
    for edu in resume.education:
        parts += [edu.degree, edu.field, edu.year]
    for cert in resume.certifications:
        parts += [cert.name, cert.issuer, cert.year]
    return numbers_in(" ".join(parts))


def _problem(text: str, allowed: set[str], terms: list[str]) -> str | None:
    """Why this text can't be kept, or None if it is fine."""
    if numbers_in(text) - allowed:
        return "it added a number"
    term = _banned_term(text, terms)
    return f"it mentioned {term}" if term else None


def _check_bullets(
    role: TailoredRole, resume: MasterResume, terms: list[str], notes: list[str]
) -> TailoredRole:
    title = resume.roles[role.role].title
    originals = resume.roles[role.role].bullets
    kept: list[TailoredBullet] = []
    used: set[int] = set()
    for b in role.bullets:
        if not 0 <= b.source < len(originals):
            notes.append(f"Removed a bullet that wasn't in your resume ({title}).")
            continue
        if b.source in used:
            continue  # the same bullet twice: keep the first
        used.add(b.source)
        original = originals[b.source]
        reason = _problem(b.text, numbers_in(original), terms)
        if reason:
            notes.append(f"Kept your original wording for a {title} bullet: {reason}.")
            b = TailoredBullet(source=b.source, text=original)
        kept.append(b)
    return TailoredRole(role=role.role, bullets=kept)


def _check_roles(
    roles: list[TailoredRole], resume: MasterResume, terms: list[str], notes: list[str]
) -> list[TailoredRole]:
    checked: list[TailoredRole] = []
    seen: set[int] = set()
    for role in roles:
        if not 0 <= role.role < len(resume.roles) or role.role in seen:
            continue
        seen.add(role.role)
        checked.append(_check_bullets(role, resume, terms, notes))
    for i, original in enumerate(resume.roles):
        if i not in seen:
            bullets = [TailoredBullet(source=j, text=t) for j, t in enumerate(original.bullets)]
            checked.append(TailoredRole(role=i, bullets=bullets))
    return checked


def _check_summary(
    summary: str, resume: MasterResume, terms: list[str], notes: list[str]
) -> str:
    reason = _problem(summary, _resume_numbers(resume), terms)
    if not reason:
        return summary
    notes.append(f"Kept your original summary: {reason}.")
    return resume.summary


def _norm(text: str) -> str:
    """Casefolded, with every kind of space (non-breaking too) turned into one plain space."""
    return " ".join(text.casefold().split())


def _has_phrase(phrase: str, text: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) is not None


def _vocabulary(resume: MasterResume) -> list[str]:
    parts = [*resume.skills]
    for role in resume.roles:
        parts += [role.title, role.employer]
    for edu in resume.education:
        parts += [edu.school, edu.degree, edu.field]
    for cert in resume.certifications:
        parts.append(cert.name)
    return [_norm(p) for p in parts if p.strip()]


def _prose(resume: MasterResume) -> list[str]:
    parts = [resume.summary, *(b for role in resume.roles for b in role.bullets)]
    return [_norm(p) for p in parts if p.strip()]


def _headline_phrases(text: str) -> list[str]:
    phrases = (p.strip(PHRASE_STRIP + " ") for p in HEADLINE_SPLIT_RE.split(_norm(text)))
    return [p for p in phrases if p]


def _phrase_allowed(phrase: str, original: str, vocabulary: list[str], prose: list[str]) -> bool:
    if _has_phrase(phrase, original) or any(_has_phrase(phrase, v) for v in vocabulary):
        return True
    return len(phrase.split()) >= 2 and any(_has_phrase(phrase, p) for p in prose)


def _headline_problem(text: str, original: str, resume: MasterResume, terms: list[str]) -> str | None:
    if len(text) > HEADLINE_CHARS:
        return "it was too long"
    if numbers_in(text) - (_resume_numbers(resume) | numbers_in(original)):
        return "it added a number"
    term = _banned_term(text, terms)
    if term:
        return f"it mentioned {term}"
    vocabulary, prose, source = _vocabulary(resume), _prose(resume), _norm(original)
    if not all(_phrase_allowed(p, source, vocabulary, prose) for p in _headline_phrases(text)):
        return "it used wording that isn't in your resume"
    return None


def _check_headline(headline: str, original: str, resume: MasterResume, terms: list[str],
                    notes: list[str]) -> str:
    if not original.strip():
        return ""
    if not headline.strip():
        return original
    reason = _headline_problem(headline.strip(), original, resume, terms)
    if not reason:
        return headline.strip()
    notes.append(f"Kept your original headline: {reason}.")
    return original


def _check_skills(skills: list[str], resume: MasterResume, notes: list[str]) -> list[str]:
    real = {s.casefold() for s in resume.skills}
    kept: list[str] = []
    for skill in skills:
        if skill.casefold() in real:
            kept.append(skill)
        else:
            notes.append(f"Removed skill not in your resume: {skill}.")
    return kept


def _check_letter(
    letter: CoverLetter, resume: MasterResume, terms: list[str], notes: list[str]
) -> CoverLetter:
    allowed = _resume_numbers(resume)
    kept: list[str] = []
    for paragraph in letter.paragraphs:
        if _problem(paragraph, allowed, terms):
            notes.append("Removed a cover letter paragraph that mentioned something not in your resume.")
        else:
            kept.append(paragraph)
    greeting = _letter_line(letter.greeting, DEFAULT_GREETING, "greeting", allowed, terms, notes)
    sign_off = _letter_line(letter.sign_off, DEFAULT_SIGN_OFF, "sign-off", allowed, terms, notes)
    return letter.model_copy(update={"paragraphs": kept, "greeting": greeting, "sign_off": sign_off})


def _letter_line(text: str, default: str, what: str, allowed: set[str], terms: list[str],
                 notes: list[str]) -> str:
    """The drafted greeting or sign-off, or a standard one when it is too long or not supported."""
    if len(text) > LETTER_LINE_CHARS:
        notes.append(f"Used a standard {what}: the drafted one was too long.")
        return default
    if _problem(text, allowed, terms):
        notes.append(f"Used a standard {what}: the drafted one mentioned something not in your resume.")
        return default
    return text


def code_check(
    draft: Draft, resume: MasterResume, profile: SearchProfile, headline: str = ""
) -> tuple[Draft, list[str]]:
    """Return a corrected copy of the draft and the note lines for notes.md."""
    terms = profile.do_not_claim
    notes: list[str] = []
    content = TailoredContent(
        headline=_check_headline(draft.content.headline, headline, resume, terms, notes),
        summary=_check_summary(draft.content.summary, resume, terms, notes),
        roles=_check_roles(draft.content.roles, resume, terms, notes),
        skills=_check_skills(draft.content.skills, resume, notes),
    )
    letter = _check_letter(draft.letter, resume, terms, notes)
    return Draft(content=content, letter=letter, changes=list(draft.changes), not_applied=list(draft.not_applied)), notes
