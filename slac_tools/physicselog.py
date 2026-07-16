"""Programmatic submission to the SLAC physics electronic logbook."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

import img2pdf
from PIL import Image


class PhysicsElogError(Exception):
    """Raised when elog submission fails."""


@dataclass(frozen=True)
class LogbookConfig:
    """Paths and settings for logbook destinations."""

    lcls_data_dir: Path = Path("/u1/lcls/physics/logbook/data")
    lcls2_data_dir: Path = Path("/u1/lcls/physics/logbook/lcls2/data")
    facet_data_dir: Path = Path("/u1/facet/physics/logbook/data")
    tmp_dir: Path = Path("/tmp")
    thumbnail_max_size: tuple[int, int] = (500, 500)


def submit_entry(
    logbook: str,
    username: str,
    title: str,
    text: str | None = None,
    attachment: str | Path | None = None,
    thumbnail: str | Path | None = None,
    *,
    config: LogbookConfig | None = None,
) -> Path:
    """Submit an entry to the physics elog.

    Returns the base path (without extension) of the submitted files.
    For printer-routed logbooks, returns the path to the printed file.
    """
    if config is None:
        config = LogbookConfig()

    if not title:
        raise PhysicsElogError("Cannot submit an entry without a title.")

    data_dir = _resolve_data_dir(logbook, config)
    if data_dir is None:
        _send_to_printer(Path(attachment) if attachment else None, f"physics-{logbook}log")
        return Path(str(attachment)) if attachment else Path()

    timestamp = datetime.now()
    time_string = timestamp.strftime("%Y-%m-%dT%H:%M:%S")
    base_name = time_string + "-00"

    tmp_xml = config.tmp_dir / f"{base_name}.xml"
    tmp_pdf = config.tmp_dir / f"{base_name}.pdf"
    tmp_png = config.tmp_dir / f"{base_name}.png"

    attachment_filename: str | None = None
    thumbnail_filename: str | None = None

    if attachment is not None:
        attachment_path = Path(attachment)
        _convert_to_pdf(attachment_path, tmp_pdf)
        attachment_filename = f"{base_name}.pdf"

        if thumbnail is not None:
            shutil.copyfile(thumbnail, tmp_png)
        else:
            _generate_thumbnail(attachment_path, tmp_png, config.thumbnail_max_size)
        thumbnail_filename = f"{base_name}.png"

    xml_content = _build_entry_xml(
        username=username,
        title=title,
        text=text,
        attachment_filename=attachment_filename,
        thumbnail_filename=thumbnail_filename,
        timestamp=timestamp,
    )
    tmp_xml.write_text(xml_content)

    _copy_to_logbook(config.tmp_dir / base_name, data_dir)
    return config.tmp_dir / base_name


def _resolve_data_dir(logbook: str, config: LogbookConfig) -> Path | None:
    """Map logbook name to its data directory. Returns None for printer-routed logbooks."""
    dirs = {
        "lcls": config.lcls_data_dir,
        "lcls2": config.lcls2_data_dir,
        "facet": config.facet_data_dir,
    }
    return dirs.get(logbook)


def _build_entry_xml(
    username: str,
    title: str,
    text: str | None,
    attachment_filename: str | None,
    thumbnail_filename: str | None,
    timestamp: datetime,
) -> str:
    """Build the XML string for a logbook entry."""
    log_entry = Element(None)
    log_entry.attrib["type"] = "LOGENTRY"

    severity = SubElement(log_entry, "severity")
    severity.text = "NONE"

    location = SubElement(log_entry, "location")
    location.text = "not set"

    keywords = SubElement(log_entry, "keywords")
    keywords.text = "none"

    time_tag = SubElement(log_entry, "time")
    time_tag.text = timestamp.strftime("%H:%M:%S")

    isodate = SubElement(log_entry, "isodate")
    isodate.text = timestamp.strftime("%Y-%m-%d")

    author = SubElement(log_entry, "author")
    author.text = username

    category = SubElement(log_entry, "category")
    category.text = "USERLOG"

    title_tag = SubElement(log_entry, "title")
    title_tag.text = title

    time_string = timestamp.strftime("%Y-%m-%dT%H:%M:%S")
    metainfo = SubElement(log_entry, "metainfo")
    metainfo.text = f"{time_string}-00.xml"

    if attachment_filename is not None:
        link = SubElement(log_entry, "link")
        link.text = attachment_filename

    if thumbnail_filename is not None:
        file_tag = SubElement(log_entry, "file")
        file_tag.text = thumbnail_filename

    # The logbook parser requires the text tag to come last.
    text_tag = SubElement(log_entry, "text")
    text_tag.text = text if text else " "

    raw = tostring(log_entry, encoding="unicode")
    formatted = re.sub(r"(?=<[^/].*>)", "\n", raw)
    return formatted.lstrip("\n") + "\n"


def _generate_thumbnail(image_path: Path, output_path: Path, max_size: tuple[int, int]) -> None:
    """Create a resized PNG thumbnail using Pillow."""
    with Image.open(image_path) as img:
        img.thumbnail(max_size)
        img.save(output_path, "PNG")


def _convert_to_pdf(image_path: Path, output_path: Path) -> None:
    """Convert image to PDF using img2pdf (lossless)."""
    with open(output_path, "wb") as f:
        f.write(img2pdf.convert(str(image_path)))


def _copy_to_logbook(base_path: Path, data_dir: Path) -> None:
    """Copy .xml, .pdf, .png files to the logbook pickup directory."""
    for ext in (".xml", ".pdf", ".png"):
        src = base_path.with_suffix(ext)
        if src.exists():
            shutil.copy(src, data_dir)


def _send_to_printer(image_path: Path | None, printer: str) -> None:
    """Convert to PostScript and print via lpr."""
    if image_path is None:
        raise PhysicsElogError("Cannot print without an attachment.")
    ps_path = image_path.with_suffix(".ps")
    with Image.open(image_path) as img:
        img.save(ps_path, "EPS")
    subprocess.run(["lpr", "-P", printer, str(ps_path)], check=True)


def main() -> None:
    """CLI entry point for physics-elog."""
    import argparse

    parser = argparse.ArgumentParser(description="Submit an entry to the physics elog")
    parser.add_argument("logbook", help="Logbook name: lcls, lcls2, facet, or custom")
    parser.add_argument("username", help="Author username")
    parser.add_argument("attachment", help="Path to image attachment")
    parser.add_argument("title", help="Entry title")
    parser.add_argument("text", nargs="?", default=None, help="Entry body text")
    parser.add_argument("--thumbnail", default=None, help="Path to thumbnail (auto-generated if omitted)")

    args = parser.parse_args()
    result = submit_entry(
        logbook=args.logbook,
        username=args.username,
        title=args.title,
        text=args.text,
        attachment=args.attachment,
        thumbnail=args.thumbnail,
    )
    print(result)


if __name__ == "__main__":
    main()
