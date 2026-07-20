"""Parse DailyMed Structured Product Labeling (SPL) XML into RAG chunks.

The bulk DailyMed downloads contain HL7 v3 XML, sometimes nested inside more
than one ZIP.  This module deliberately uses only the XML narrative supplied by
DailyMed and keeps the section and label identifiers needed for citations and
incremental updates.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Protocol
from xml.etree import ElementTree as ET


BLOCK_TAGS = {
    "br",
    "caption",
    "item",
    "list",
    "paragraph",
    "td",
    "th",
    "tr",
}


class TokenCodec(Protocol):
    def encode(self, text: str) -> list[int]: ...

    def decode(self, tokens: list[int]) -> str: ...


class TiktokenCodec:
    """Token codec matching OpenAI embedding models."""

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        try:
            import tiktoken
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "tiktoken is required for token-accurate chunking; "
                "run `pip install -r requirements.txt`"
            ) from exc
        self._encoding = tiktoken.get_encoding(encoding_name)

    def encode(self, text: str) -> list[int]:
        return self._encoding.encode(text)

    def decode(self, tokens: list[int]) -> str:
        return self._encoding.decode(tokens)


@dataclass(frozen=True)
class SplDocument:
    source_file: str
    document_id: str
    set_id: str
    version: str
    effective_time: str
    label_type_code: str
    label_type: str
    title: str
    manufacturer: str
    sections: tuple["SplSection", ...]


@dataclass(frozen=True)
class SplSection:
    index: int
    code: str
    title: str
    text: str


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, str | int]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _direct_child(root: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in root if _local_name(child.tag) == name), None)


def _attribute(element: ET.Element | None, name: str) -> str:
    return element.get(name, "") if element is not None else ""


def _element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return _normalize_inline(" ".join(element.itertext()))


def _normalize_inline(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _narrative_text(element: ET.Element) -> str:
    pieces: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.text:
            pieces.append(node.text)
        for child in node:
            walk(child)
            if _local_name(child.tag) in BLOCK_TAGS:
                pieces.append("\n")
            if child.tail:
                pieces.append(child.tail)

    walk(element)
    lines = [_normalize_inline(line) for line in "".join(pieces).splitlines()]
    return "\n".join(line for line in lines if line)


def parse_spl(xml_bytes: bytes, source_file: str = "") -> SplDocument:
    """Parse one SPL XML document.

    Raises ``ValueError`` for XML that is valid but is not a usable SPL label.
    """

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"invalid XML in {source_file or '<bytes>'}: {exc}") from exc

    if _local_name(root.tag) != "document":
        raise ValueError(f"not an SPL document: {source_file or '<bytes>'}")

    document_id = _attribute(_direct_child(root, "id"), "root")
    set_id = _attribute(_direct_child(root, "setId"), "root")
    version = _attribute(_direct_child(root, "versionNumber"), "value")
    effective_time = _attribute(_direct_child(root, "effectiveTime"), "value")
    document_code = _direct_child(root, "code")
    title = _element_text(_direct_child(root, "title"))

    manufacturer = ""
    author = _direct_child(root, "author")
    if author is not None:
        manufacturer_node = next(
            (node for node in author.iter() if _local_name(node.tag) == "name"), None
        )
        manufacturer = _element_text(manufacturer_node)

    sections: list[SplSection] = []
    for index, section in enumerate(
        (node for node in root.iter() if _local_name(node.tag) == "section")
    ):
        narrative = _direct_child(section, "text")
        if narrative is None:
            continue
        text = _narrative_text(narrative)
        if not text:
            continue
        code_node = _direct_child(section, "code")
        sections.append(
            SplSection(
                index=index,
                code=code_node.get("code", "") if code_node is not None else "",
                title=_element_text(_direct_child(section, "title")) or "Untitled section",
                text=text,
            )
        )

    if not set_id or not sections:
        raise ValueError(f"SPL has no setId or narrative sections: {source_file or '<bytes>'}")

    return SplDocument(
        source_file=source_file,
        document_id=document_id,
        set_id=set_id,
        version=version,
        effective_time=effective_time,
        label_type_code=document_code.get("code", "") if document_code is not None else "",
        label_type=document_code.get("displayName", "") if document_code is not None else "",
        title=title,
        manufacturer=manufacturer,
        sections=tuple(sections),
    )


def _iter_zip_xml(archive: zipfile.ZipFile, prefix: str = "") -> Iterator[tuple[str, bytes]]:
    for member in archive.infolist():
        if member.is_dir():
            continue
        name = f"{prefix}{member.filename}"
        lowered = member.filename.lower()
        if lowered.endswith(".xml"):
            yield name, archive.read(member)
        elif lowered.endswith(".zip"):
            with archive.open(member) as nested_file:
                nested_bytes = nested_file.read()
            try:
                with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested_archive:
                    yield from _iter_zip_xml(nested_archive, prefix=f"{name}!/")
            except zipfile.BadZipFile:
                continue


def iter_xml_files(path: str | Path) -> Iterator[tuple[str, bytes]]:
    """Yield XML payloads from an XML file, ZIP file, or directory recursively."""

    source = Path(path)
    if source.is_dir():
        for candidate in sorted(source.rglob("*")):
            if candidate.suffix.lower() in {".xml", ".zip"}:
                yield from iter_xml_files(candidate)
        return
    if source.suffix.lower() == ".xml":
        yield str(source), source.read_bytes()
        return
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            yield from _iter_zip_xml(archive, prefix=f"{source}!/")
        return
    raise ValueError(f"expected an XML file, ZIP file, or directory: {source}")


def iter_spl_documents(paths: Iterable[str | Path]) -> Iterator[SplDocument]:
    for path in paths:
        for source_file, payload in iter_xml_files(path):
            try:
                yield parse_spl(payload, source_file)
            except ValueError:
                # Bulk archives can include non-label XML resources.
                continue


def chunk_spl(
    document: SplDocument,
    *,
    chunk_size: int = 800,
    overlap: int = 120,
    codec: TokenCodec | None = None,
) -> Iterator[Chunk]:
    """Split an SPL by section first, then by token windows.

    The repeated label/section header makes each returned chunk independently
    understandable when it is retrieved without neighboring chunks.
    """

    if chunk_size < 100:
        raise ValueError("chunk_size must be at least 100 tokens")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")
    codec = codec or TiktokenCodec()

    for section in document.sections:
        header = f"Drug label: {document.title}\nSection: {section.title}\n\n"
        header_tokens = codec.encode(header)
        body_budget = chunk_size - len(header_tokens)
        if body_budget <= overlap:
            raise ValueError("chunk_size is too small for the label and section header")
        body_tokens = codec.encode(section.text)
        step = body_budget - overlap

        for part_index, start in enumerate(range(0, len(body_tokens), step)):
            body_part = body_tokens[start : start + body_budget]
            if not body_part:
                break
            text = header + codec.decode(body_part).strip()
            identity = ":".join(
                [
                    document.set_id,
                    document.version,
                    section.code,
                    str(section.index),
                    str(part_index),
                ]
            )
            chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            metadata: dict[str, str | int] = {
                "source": "DailyMed",
                "source_file": document.source_file,
                "source_url": (
                    "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
                    f"{document.set_id}"
                ),
                "document_id": document.document_id,
                "set_id": document.set_id,
                "version": document.version,
                "effective_time": document.effective_time,
                "label_type_code": document.label_type_code,
                "label_type": document.label_type,
                "label_title": document.title,
                "manufacturer": document.manufacturer,
                "section_index": section.index,
                "section_code": section.code,
                "section_title": section.title,
                "chunk_index": part_index,
                "token_count": len(header_tokens) + len(body_part),
            }
            yield Chunk(id=chunk_id, text=text, metadata=metadata)
            if start + body_budget >= len(body_tokens):
                break
