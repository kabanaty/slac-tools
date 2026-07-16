"""Tests for slac_tools.physicselog."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from xml.etree.ElementTree import fromstring

import pytest
from PIL import Image

from slac_tools.physicselog import (
    LogbookConfig,
    PhysicsElogError,
    _build_entry_xml,
    _convert_to_pdf,
    _generate_thumbnail,
    _resolve_data_dir,
    submit_entry,
)


@pytest.fixture
def config(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return LogbookConfig(
        lcls_data_dir=data_dir,
        lcls2_data_dir=data_dir,
        facet_data_dir=data_dir,
        tmp_dir=tmp_path,
    )


@pytest.fixture
def test_image(tmp_path):
    img_path = tmp_path / "test.png"
    img = Image.new("RGB", (1000, 800), color="red")
    img.save(img_path)
    return img_path


class TestResolveDataDir:
    def test_lcls(self):
        cfg = LogbookConfig()
        assert _resolve_data_dir("lcls", cfg) == cfg.lcls_data_dir

    def test_lcls2(self):
        cfg = LogbookConfig()
        assert _resolve_data_dir("lcls2", cfg) == cfg.lcls2_data_dir

    def test_facet(self):
        cfg = LogbookConfig()
        assert _resolve_data_dir("facet", cfg) == cfg.facet_data_dir

    def test_unknown_returns_none(self):
        cfg = LogbookConfig()
        assert _resolve_data_dir("mcc", cfg) is None


class TestBuildEntryXml:
    def _parse(self, xml_str):
        """Wrap in a root element for parsing — the elog format has no root wrapper."""
        return fromstring(f"<root>{xml_str}</root>")

    def test_basic_structure(self):
        ts = datetime(2024, 3, 15, 10, 30, 45)
        xml_str = _build_entry_xml(
            username="testuser",
            title="Test Title",
            text="Body text",
            attachment_filename=None,
            thumbnail_filename=None,
            timestamp=ts,
        )
        root = self._parse(xml_str)
        assert root.find("author").text == "testuser"
        assert root.find("title").text == "Test Title"
        assert root.find("text").text == "Body text"
        assert root.find("category").text == "USERLOG"
        assert root.find("isodate").text == "2024-03-15"
        assert root.find("time").text == "10:30:45"

    def test_text_tag_is_last(self):
        ts = datetime(2024, 1, 1, 0, 0, 0)
        xml_str = _build_entry_xml("u", "t", "body", "att.pdf", "thumb.png", ts)
        root = self._parse(xml_str)
        children = list(root)
        assert children[-1].tag == "text"

    def test_attachment_and_thumbnail_tags(self):
        ts = datetime(2024, 1, 1, 0, 0, 0)
        xml_str = _build_entry_xml("u", "t", None, "file.pdf", "thumb.png", ts)
        root = self._parse(xml_str)
        assert root.find("link").text == "file.pdf"
        assert root.find("file").text == "thumb.png"

    def test_no_attachment_means_no_link_tag(self):
        ts = datetime(2024, 1, 1, 0, 0, 0)
        xml_str = _build_entry_xml("u", "t", None, None, None, ts)
        root = self._parse(xml_str)
        assert root.find("link") is None
        assert root.find("file") is None

    def test_empty_text_becomes_space(self):
        ts = datetime(2024, 1, 1, 0, 0, 0)
        xml_str = _build_entry_xml("u", "t", None, None, None, ts)
        root = self._parse(xml_str)
        assert root.find("text").text == " "


class TestGenerateThumbnail:
    def test_creates_resized_png(self, test_image, tmp_path):
        out = tmp_path / "thumb.png"
        _generate_thumbnail(test_image, out, (500, 500))
        assert out.exists()
        with Image.open(out) as img:
            assert img.width <= 500
            assert img.height <= 500

    def test_preserves_aspect_ratio(self, test_image, tmp_path):
        out = tmp_path / "thumb.png"
        _generate_thumbnail(test_image, out, (500, 500))
        with Image.open(out) as img:
            assert img.width == 500
            assert img.height == 400


class TestConvertToPdf:
    def test_creates_valid_pdf(self, test_image, tmp_path):
        out = tmp_path / "output.pdf"
        _convert_to_pdf(test_image, out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"


class TestSubmitEntry:
    def test_empty_title_raises(self, config):
        with pytest.raises(PhysicsElogError, match="title"):
            submit_entry("lcls", "user", "", config=config)

    def test_full_submission_with_attachment(self, config, test_image):
        result = submit_entry(
            logbook="lcls2",
            username="testuser",
            title="Test Entry",
            text="Some text",
            attachment=test_image,
            config=config,
        )
        assert result.suffix == ""
        data_dir = config.lcls2_data_dir
        xml_files = list(data_dir.glob("*.xml"))
        pdf_files = list(data_dir.glob("*.pdf"))
        png_files = list(data_dir.glob("*.png"))
        assert len(xml_files) == 1
        assert len(pdf_files) == 1
        assert len(png_files) == 1

    def test_submission_without_attachment(self, config):
        result = submit_entry(
            logbook="lcls",
            username="testuser",
            title="Text Only",
            text="Just text",
            config=config,
        )
        data_dir = config.lcls_data_dir
        xml_files = list(data_dir.glob("*.xml"))
        assert len(xml_files) == 1
        assert len(list(data_dir.glob("*.pdf"))) == 0

    @patch("slac_tools.physicselog._send_to_printer")
    def test_unknown_logbook_routes_to_printer(self, mock_print, config, test_image):
        submit_entry(
            logbook="mcc",
            username="testuser",
            title="Print This",
            attachment=test_image,
            config=config,
        )
        mock_print.assert_called_once()
        assert "physics-mcclog" in str(mock_print.call_args)
