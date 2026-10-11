"""Optional public document downloader that preserves successes when offline."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.config import ROOT


def fetch_corpus(url_list: Path, output_dir: Path, timeout: float = 10) -> list[dict[str, str]]:
    """Download HTTP(S) URLs as UTF-8 text; report failures without crashing offline."""
    urls = [
        line.strip()
        for line in url_list.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for url in urls:
        try:
            if urlparse(url).scheme not in {"http", "https"}:
                raise ValueError("Only HTTP and HTTPS document URLs are supported")
            request = Request(url, headers={"User-Agent": "Northwind-RAG-corpus/0.1"})
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                text = response.read().decode(charset)
            name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".txt"
            path = output_dir / name
            path.write_text(text, encoding="utf-8")
            outcomes.append({"url": url, "status": "downloaded", "path": str(path)})
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, LookupError) as error:
            outcomes.append({"url": url, "status": "skipped", "reason": str(error)})
    return outcomes


def main() -> None:
    """Download a URL list, printing a per-document success/failure manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url_list", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "docs")
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    print(json.dumps(fetch_corpus(args.url_list, args.output_dir, args.timeout), indent=2))


if __name__ == "__main__":
    main()
