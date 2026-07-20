#!/usr/bin/env python3
"""Build newline-delimited RAG chunks from DailyMed SPL XML/ZIP files."""

from __future__ import annotations

import argparse
import json
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import certifi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careplans.rag.dailymed import chunk_spl, iter_spl_documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", help="XML/ZIP files or directories")
    parser.add_argument("--url", action="append", default=[], help="DailyMed XML/ZIP URL")
    parser.add_argument(
        "--set-id",
        action="append",
        default=[],
        help="Download the current XML for a DailyMed SET ID (repeatable)",
    )
    parser.add_argument("--output", required=True, help="Output JSONL path")
    parser.add_argument("--chunk-size", type=int, default=800, help="Maximum tokens per chunk")
    parser.add_argument("--overlap", type=int, default=120, help="Overlapping body tokens")
    parser.add_argument("--limit", type=int, help="Stop after this many SPL documents")
    return parser.parse_args()


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "care-plan-generator/1.0"})
    tls_context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(
        request, timeout=120, context=tls_context
    ) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)


def main() -> int:
    args = parse_args()
    if not args.inputs and not args.url and not args.set_id:
        raise SystemExit("provide at least one input, --url, or --set-id")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    document_count = 0
    chunk_count = 0

    with tempfile.TemporaryDirectory(prefix="dailymed-") as temp_dir:
        paths = [Path(item) for item in args.inputs]
        urls = list(args.url)
        urls.extend(
            f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{set_id}.xml"
            for set_id in args.set_id
        )
        for index, url in enumerate(urls):
            downloaded = Path(temp_dir) / f"download-{index}.data"
            print(f"Downloading {url}", file=sys.stderr)
            download(url, downloaded)
            suffix = ".zip" if zipfile.is_zipfile(downloaded) else ".xml"
            destination = downloaded.with_suffix(suffix)
            downloaded.rename(destination)
            paths.append(destination)

        with output.open("w", encoding="utf-8") as out:
            for document in iter_spl_documents(paths):
                for chunk in chunk_spl(
                    document, chunk_size=args.chunk_size, overlap=args.overlap
                ):
                    out.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
                    chunk_count += 1
                document_count += 1
                if document_count % 100 == 0:
                    print(
                        f"Processed {document_count} labels / {chunk_count} chunks",
                        file=sys.stderr,
                    )
                if args.limit is not None and document_count >= args.limit:
                    break

    print(
        f"Wrote {chunk_count} chunks from {document_count} labels to {output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
