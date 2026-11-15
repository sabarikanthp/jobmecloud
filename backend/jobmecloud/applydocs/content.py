"""The content of a tailored resume and cover letter, and the schema the AI fills in."""

from pydantic import BaseModel

from jobmecloud.config.profile import MasterResume


class TailoredBullet(BaseModel):
    source: int  # index into the original role's bullets
    text: str


class TailoredRole(BaseModel):
    role: int  # index into MasterResume.roles
    bullets: list[TailoredBullet]  # in display order; leaving one out drops it


class TailoredContent(BaseModel):
    headline: str  # "" when the resume has no headline
    summary: str
    roles: list[TailoredRole]
    skills: list[str]


class CoverLetter(BaseModel):
    greeting: str  # "Dear Hiring Manager,"
    paragraphs: list[str]
    sign_off: str  # "Sincerely,"


class Draft(BaseModel):
    content: TailoredContent
    letter: CoverLetter
    changes: list[str]  # what changed and why, one line each


def _str() -> dict:
    return {"type": "string"}


def _int() -> dict:
    return {"type": "integer"}


def _list(items: dict) -> dict:
    return {"type": "array", "items": items}


def _obj(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


DRAFT_SCHEMA = _obj({
    "content": _obj({
        "headline": _str(),
        "summary": _str(),
        "roles": _list(_obj({
            "role": _int(),
            "bullets": _list(_obj({"source": _int(), "text": _str()})),
        })),
        "skills": _list(_str()),
    }),
    "letter": _obj({
        "greeting": _str(),
        "paragraphs": _list(_str()),
        "sign_off": _str(),
    }),
    "changes": _list(_str()),
})


def original_content(resume: MasterResume, headline: str = "") -> TailoredContent:
    """Every bullet, in order, in the original wording."""
    return TailoredContent(
        headline=headline,
        summary=resume.summary,
        roles=[
            TailoredRole(
                role=i,
                bullets=[TailoredBullet(source=j, text=b) for j, b in enumerate(r.bullets)],
            )
            for i, r in enumerate(resume.roles)
        ],
        skills=list(resume.skills),
    )
