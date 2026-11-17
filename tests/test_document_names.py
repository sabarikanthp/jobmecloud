import pytest

from jobmecloud.applydocs.output import document_filename


@pytest.mark.parametrize("person,employer,title,kind,suffix,expected", [
    ("Jordan Example", "Initech Health", "Lead Director", "resume", ".docx", "Jordan_Example_Initech_LeadDirector.docx"),
    ("Jordan Example", "Initech Health", "Lead Director", "cover_letter", ".docx", "Jordan_Example_Initech_LeadDirector_Cover.docx"),
    ("Jordan Example", "Globex Financial", "VP/Director, Software Engineering – Document Management",
     "resume", ".pdf", "Jordan_Example_Globex_VPDirectorSoftwareEngineering.pdf"),
    ("Jordan Example", "Hooli International", "Director, DevCon Platform Engineering", "resume", ".docx",
     "Jordan_Example_Hooli_DirectorDevConPlatformEngineering.docx"),
    ("Jordan Example", "Umbrella Press", "Director, Software Engineering", "resume", ".docx",
     "Jordan_Example_UmbrellaPress_DirectorSoftwareEngineering.docx"),
    ("Jordan Example", "Acme, Inc.", "VP", "resume", ".docx", "Jordan_Example_Acme_VP.docx"),
])
def test_document_names_follow_the_pattern(person, employer, title, kind, suffix, expected):
    assert document_filename(person, employer, title, kind, suffix) == expected


def test_a_missing_name_title_or_employer_never_leaves_a_gap_or_an_unsafe_name():
    assert document_filename("", "Initech Health", "Lead Director", "resume", ".docx") == "Initech_LeadDirector.docx"
    assert document_filename("Sabari P", "", "", "resume", ".docx") == "Sabari_P.docx"
    assert document_filename("", "", "", "resume", ".docx") == "Resume.docx"
    assert document_filename("", "", "", "cover_letter", ".docx") == "Cover_Letter.docx"
    unsafe = document_filename('A/B"C', "../Evil:Corp", "X\\Y*?", "resume", ".docx")
    assert not any(ch in unsafe for ch in '/\\:*?"<>|')


def test_a_very_long_title_is_cut_to_a_sensible_length():
    name = document_filename("A B", "Acme", "Senior Vice President of Global Engineering and Platform Operations",
                             "resume", ".docx")
    assert len(name) <= 80 and name.endswith(".docx")
