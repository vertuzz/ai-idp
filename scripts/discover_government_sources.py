"""Discover official publication attachments without guessing asset URLs."""

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from scripts.prepare_cord_preview import ROOT, write_json


def get_json(url):
    with urlopen(url, timeout=45) as response:
        return json.load(response)


def publication(path):
    try:
        content = get_json("https://www.gov.uk/api/content" + path)
        attachments = []
        for asset in content.get("details", {}).get("attachments", []):
            url = asset.get("url", "")
            ext = urlparse(url).path.lower().rsplit(".", 1)[-1]
            if ext in {"pdf", "docx"}:
                attachments.append(
                    {
                        "title": asset["title"],
                        "url": url,
                        "format": ext,
                        "pages_reported": asset.get("number_of_pages"),
                        "bytes_reported": asset.get("file_size"),
                    }
                )
        return {
            "publication_url": "https://www.gov.uk" + path,
            "title": content["title"],
            "content_id": content["content_id"],
            "updated_at": content.get("public_updated_at"),
            "publishers": [x["title"] for x in content.get("links", {}).get("organisations", [])],
            "attachments": attachments,
        }
    except Exception as error:
        print(f"Discovery failed for {path}: {error}", flush=True)
        return None


def main():
    paths = {
        "/government/publications/" + slug
        for slug in [
            "managing-public-money-framework-documents",
            "managing-public-money",
            "explanatory-memorandum-template-and-guidance",
            "the-green-book-templates-and-support-material",
            "impact-assessment-template-for-government-policies",
            "the-right-to-request-flexible-working-form",
            "financial-remedy-summary-of-case-form-es1",
        ]
    }
    for query in [
        "template",
        "application form",
        "guidance environmental",
        "statistical bulletin",
        "annual report accounts 2024 2025",
        "procurement policy note",
        "grant guidance",
    ]:
        result = get_json(
            "https://www.gov.uk/api/search.json?" + urlencode({"q": query, "count": 35})
        )
        paths.update(
            x["link"]
            for x in result["results"]
            if x["link"].startswith("/government/publications/")
        )
    with ThreadPoolExecutor(max_workers=6) as pool:
        publications = [x for x in pool.map(publication, sorted(paths)) if x and x["attachments"]]
    target = ROOT / "eval/cache/government-discovery.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, publications)
    for ext in ["docx", "pdf"]:
        print(f"\n{ext.upper()} CANDIDATES", flush=True)
        for pub in publications:
            assets = [a for a in pub["attachments"] if a["format"] == ext]
            if assets:
                print(
                    pub["publication_url"].rsplit("/", 1)[-1],
                    "|",
                    [a["title"] for a in assets[:3]],
                    flush=True,
                )


if __name__ == "__main__":
    main()
