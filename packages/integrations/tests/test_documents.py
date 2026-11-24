from pathlib import Path

import pytest
from freight_agents.integrations.documents import DocumentError, pdf_text
from reportlab.pdfgen import canvas


def test_pdf_text_reads_every_page(tmp_path: Path) -> None:
    path = tmp_path / "two.pdf"
    page = canvas.Canvas(str(path), invariant=True)
    page.drawString(72, 720, "TENDER ID: LHG-104201")
    page.showPage()
    page.drawString(72, 720, "WEIGHT: 43,990 lbs")
    page.save()
    text = pdf_text(path)
    assert "LHG-104201" in text
    assert "43,990" in text


def test_a_file_that_is_not_a_pdf_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "fake.pdf"
    path.write_text("not a pdf")
    with pytest.raises(DocumentError):
        pdf_text(path)
