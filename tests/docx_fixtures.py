import io
import re
import zipfile

import docx

from jobmecloud.config.profile import Certification, Education, MasterResume, ResumeRole

HEADLINE = "Engineering Leader | Data Platforms | Healthcare Technology"
SUMMARY = "Data engineer with seven years of experience building reliable pipelines."
NORTHWIND = [
    ("Built pipelines: ", "moved 2 TB of data daily with Airflow."),
    ("Cut costs: ", "reduced warehouse spend by 30 percent."),
    ("Led migration: ", "moved reporting to a new warehouse."),
]
CONTOSO = [
    ("Shipped reports: ", "delivered weekly dashboards for clinic managers."),
    ("Improved quality: ", "added tests that caught bad data early."),
]

FIXTURE_READING = MasterResume(
    summary=SUMMARY,
    roles=[
        ResumeRole(employer="Northwind Labs", title="Senior Engineer", start="2021", end="2025",
                   bullets=[b + n for b, n in NORTHWIND]),
        ResumeRole(employer="Contoso Health", title="Engineer", start="2018", end="2021",
                   bullets=[b + n for b, n in CONTOSO]),
    ],
    skills=["Python", "SQL", "Airflow"],
    education=[Education(school="State University", degree="B.S.", field="Computer Science", year="2018")],
    certifications=[Certification(name="Example Cloud Practitioner")],
)

FIXTURE_LABELS: dict[int, str] = {
    **{i: "keep" for i in range(17)},
    0: "contact", 1: "contact", 2: "headline", 4: "summary",
    6: "title", 7: "bullet:0:0", 8: "bullet:0:1", 9: "bullet:0:2",
    10: "title", 11: "bullet:1:0", 12: "bullet:1:1",
    14: "skills",
}


def _bullet(doc: "docx.document.Document", bold: str, normal: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.add_run(bold).bold = True
    p.add_run(normal)


def make_resume_docx() -> bytes:
    doc = docx.Document()
    doc.add_paragraph("Jordan Example", style="Title")
    doc.add_paragraph("jordan@example.com · Springfield")
    doc.add_paragraph(HEADLINE)
    doc.add_paragraph("Summary", style="Heading 1")
    doc.add_paragraph(SUMMARY)
    doc.add_paragraph("Experience", style="Heading 1")
    doc.add_paragraph("Northwind Labs — Senior Engineer — 2021–2025")
    for bold, normal in NORTHWIND:
        _bullet(doc, bold, normal)
    doc.add_paragraph("Contoso Health — Engineer — 2018–2021")
    for bold, normal in CONTOSO:
        _bullet(doc, bold, normal)
    doc.add_paragraph("Skills", style="Heading 1")
    doc.add_paragraph("Python, SQL, Airflow")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "B.S. Computer Science"
    table.cell(0, 1).text = "State University, 2018"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def set_app_pages(data: bytes, pages: int) -> bytes:
    """Rewrite docProps/app.xml <Pages>, adding the element if it is missing."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "docProps/app.xml":
                xml = content.decode("utf-8")
                element = f"<Pages>{pages}</Pages>"
                if re.search(r"<Pages>.*?</Pages>|<Pages\s*/>", xml):
                    xml = re.sub(r"<Pages>.*?</Pages>|<Pages\s*/>", element, xml, count=1)
                else:
                    xml = re.sub(r"(</Properties>)", element + r"\1", xml, count=1)
                content = xml.encode("utf-8")
            zout.writestr(item, content)
    return out.getvalue()
