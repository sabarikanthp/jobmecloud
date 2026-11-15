import re

from pydantic import BaseModel

from jobmecloud.config.profile import MasterResume, ResumeRole
from jobmecloud.llm.structured import complete_json
from jobmecloud.llm.types import Provider
from jobmecloud.resumes.docx_text import iter_paragraphs

LABEL_RE = re.compile(r"^(contact|headline|title|summary|skills|keep|bullet:\d+:\d+)$")
MAP_FAIL_COPY = "JobMe couldn't find the parts of this resume. You can still use it as-is."
MAP_INPUT_CHARS = 40_000


class MappedParagraph(BaseModel):
    index: int
    text: str
    label: str


class ResumeMapping(BaseModel):
    paragraphs: list[MappedParagraph]
    # The identity keys of the reading's roles when the labels were made. Empty means
    # unknown (a mapping saved before keys existed): treated as matching the reading.
    role_keys: list[str] = []
    # True when the reading's jobs changed in a way the labels could not follow.
    stale: bool = False

    def mapped(self) -> bool:
        return any(p.label != "keep" for p in self.paragraphs)


def role_key(role: ResumeRole) -> str:
    """A role's identity: employer, title and dates, lower-cased with spaces collapsed."""
    return "|".join(" ".join(part.split()).lower() for part in (role.employer, role.title, role.start, role.end))


def role_keys(reading: MasterResume) -> list[str]:
    return [role_key(r) for r in reading.roles]


def keys_match(mapping: ResumeMapping, reading: MasterResume) -> bool:
    """Whether the mapping's labels were made for this reading's roles (empty keys: assumed yes)."""
    return not mapping.role_keys or mapping.role_keys == role_keys(reading)


def _bullet_role(label: str) -> int | None:
    return int(label.split(":")[1]) if label.startswith("bullet:") and LABEL_RE.match(label) else None


def remap_mapping(mapping: ResumeMapping, new_reading: MasterResume) -> ResumeMapping:
    """Point the bullet labels at the same jobs in a reading whose jobs were moved.

    When a job the labels use is gone (removed, or its employer, title or dates changed),
    the labels stay as they are and the mapping is marked stale for the user to review.
    """
    new_keys = role_keys(new_reading)
    if not mapping.role_keys:
        return mapping.model_copy(update={"role_keys": new_keys})
    used = sorted({r for p in mapping.paragraphs if (r := _bullet_role(p.label)) is not None})
    taken: set[int] = set()
    moved: dict[int, int] = {}
    for old in used:
        key = mapping.role_keys[old] if old < len(mapping.role_keys) else None
        new = next((i for i, k in enumerate(new_keys) if k == key and i not in taken), None)
        if new is None:
            return mapping.model_copy(update={"stale": True})
        taken.add(new)
        moved[old] = new
    counts: dict[int, int] = {}
    paragraphs = []
    for p in mapping.paragraphs:
        label = p.label
        if (old := _bullet_role(label)) is not None:
            role = moved[old]
            label = f"bullet:{role}:{counts.get(role, 0)}"
            counts[role] = counts.get(role, 0) + 1
        paragraphs.append(MappedParagraph(index=p.index, text=p.text, label=label))
    return ResumeMapping(paragraphs=paragraphs, role_keys=new_keys, stale=False)


MAPPING_SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "label": {"type": "string"}},
                "required": ["index", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}

MAP_SYSTEM = (
    "You label the paragraphs of a resume. Each paragraph is given as '<index>: <text>'. "
    "Answer with one label per paragraph you can place, using only these labels: "
    "'contact' for the name and contact details such as email, phone, location and links, "
    "'headline' for the one-line headline or tagline directly under the name "
    "(often phrases separated by |, a dot, a bullet or a dash; it is not contact details), "
    "'title' for the job title, company name and dates heading line of each role "
    "(also the school and degree heading lines), "
    "'summary' for the summary paragraph, "
    "'skills' for the skills list, 'bullet:<role>:<bullet>' for a bullet that matches a bullet "
    "in the numbered list of roles and bullets, and 'keep' for everything else "
    "(section headings, education details, certifications). "
    "When you are unsure about a paragraph, label it 'keep'. "
    "Use each bullet label at most once. Never invent text."
)


def _reading_outline(reading: MasterResume) -> str:
    lines = []
    for r, role in enumerate(reading.roles):
        lines.append(f"role {r}: {role.title} at {role.employer}")
        lines.extend(f"  bullet:{r}:{b}: {bullet}" for b, bullet in enumerate(role.bullets))
    return "\n".join(lines)


def draft_mapping(provider: Provider, model: str, data: bytes, reading: MasterResume) -> ResumeMapping:
    paragraphs = iter_paragraphs(data)
    listing = "\n".join(f"{p.index}: {p.text}" for p in paragraphs if p.text.strip())
    prompt = (
        "Resume paragraphs:\n"
        f"\n{listing[:MAP_INPUT_CHARS]}\n\n"
        "Roles and bullets already read from this resume:\n"
        f"{_reading_outline(reading) or '(none)'}"
    )
    answer, _usage = complete_json(provider, model=model, system=MAP_SYSTEM, prompt=prompt, schema=MAPPING_SCHEMA)
    given = {item["index"]: item["label"] for item in answer["labels"]}
    mapped = [
        MappedParagraph(
            index=p.index,
            text=p.text,
            label=given.get(p.index, "keep") if p.text.strip() else "keep",
        )
        for p in paragraphs
    ]
    return clean_mapping(ResumeMapping(paragraphs=mapped, role_keys=role_keys(reading)), reading)


def clean_mapping(mapping: ResumeMapping, reading: MasterResume) -> ResumeMapping:
    seen: set[str] = set()
    cleaned = []
    for p in mapping.paragraphs:
        label = p.label
        if not LABEL_RE.match(label):
            label = "keep"
        elif label.startswith("bullet:"):
            _, role, bullet = label.split(":")
            role_i, bullet_i = int(role), int(bullet)
            valid = role_i < len(reading.roles) and bullet_i < len(reading.roles[role_i].bullets)
            label = f"bullet:{role_i}:{bullet_i}" if valid and f"{role_i}:{bullet_i}" not in seen else "keep"
            if label != "keep":
                seen.add(f"{role_i}:{bullet_i}")
        cleaned.append(MappedParagraph(index=p.index, text=p.text, label=label))
    return ResumeMapping(paragraphs=cleaned, role_keys=mapping.role_keys, stale=mapping.stale)
