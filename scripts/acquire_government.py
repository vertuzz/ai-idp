"""Download selected original GOV.UK PDF/DOCX files and retain publication metadata."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

from scripts.prepare_cord_preview import ROOT, sha256, write_json

DOCX = {
    "development": [
        ("bribery-and-corruption-assessment-template", 0),
        ("carriage-of-dangerous-goods-annual-report-template", 0),
        ("explanatory-memorandum-template-and-guidance", 0),
        ("guidance-for-seed-sourcing-grant-recipients", 0),
        ("impact-assessment-template-for-government-policies", 0),
        ("impact-assessment-template-for-government-policies", 1),
        (
            "local-restrictions-support-grants-lrsg-and-additional-restrictions-grant-arg-guidance-for-local-authorities",
            0,
        ),
        ("managing-public-money", 0),
        ("managing-public-money-framework-documents", 0),
    ],
    "calibration": [
        ("financial-remedy-summary-of-case-form-es1", 0),
        ("independent-examiners-report-template-for-receipts-and-payments-accounts", 0),
        ("the-right-to-request-flexible-working-form", 0),
    ],
    "holdout": [
        ("fcerm-business-case-templates", 2),
        ("response-template-for-applicants", 0),
        ("the-green-book-templates-and-support-material", 0),
    ],
}
PDF = {
    "development": [
        ("agroforestry-plan-pa4-complete-your-templates", 0),
        ("application-for-an-environmental-permit-part-b10-flood-risk-activities", 0),
        ("apply-for-help-with-court-and-tribunal-fees", 0),
        ("climate-change-agreements-scheme-templates-for-umbrella-and-underlying-agreements", 0),
        ("cma-informal-guidance-fairtrade-environmental-sustainability-agreement", 0),
        ("defras-draft-social-and-environmental-guidance-to-ofwat", 0),
        ("disabled-facilities-grant-dfg-delivery-guidance-for-local-authorities-in-england", 0),
        ("gce-subject-level-guidance-for-environmental-science", 0),
        (
            "granting-a-necessary-compulsory-electricity-wayleave-guidance-for-applicants-and-landowner-and-or-occupiers",
            0,
        ),
        ("humanitarian-protection-instruction", 1),
        ("procurement-policy-note-09-12-taking-account-of-bidders-past-performance", 0),
        ("procurement-policy-note-0613-promoting-tax-compliance", 0),
    ],
    "calibration": [
        ("receipts-and-payments-accounts-cc16-charity-accounting-template", 0),
        ("warm-homes-local-grant", 0),
        ("fcdo-services-annual-report-and-accounts-2024-to-2025", 0),
        ("template-holding-register-for-cattle-keepers", 0),
    ],
    "holdout": [
        ("sovereign-grant-act-2011-guidance", 0),
        ("winter-fuel-payment-claim-form", 0),
        ("the-national-gallery-annual-report-and-accounts-2024-to-2025", 0),
        ("application-for-a-vehicle-registration-certificate", 0),
    ],
}


def acquire(task):
    record = task.copy()
    path = ROOT / record["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        for attempt in range(3):
            try:
                with urlopen(record["source_url"], timeout=60) as response:
                    payload = response.read(80 * 1024**2 + 1)
                if len(payload) > 80 * 1024**2:
                    raise ValueError("Government attachment exceeded download limit")
                signature = b"%PDF" if record["format"] == "pdf" else b"PK"
                if not payload.startswith(signature):
                    raise ValueError("Government attachment has an unexpected file signature")
                path.write_bytes(payload)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
    record.update(sha256=sha256(path), bytes=path.stat().st_size, status="downloaded")
    print(f"Downloaded {record['case_id']}: {record['title']}", flush=True)
    return record


def main():
    discovery = json.loads(
        (ROOT / "eval/cache/government-discovery.json").read_text(encoding="utf-8")
    )
    publications = {p["publication_url"].rsplit("/", 1)[-1]: p for p in discovery}
    tasks = []
    for ext, selection in [("docx", DOCX), ("pdf", PDF)]:
        for split, entries in selection.items():
            for slug, index in entries:
                pub = publications[slug]
                asset = [a for a in pub["attachments"] if a["format"] == ext][index]
                case_id = f"gov-uk-{ext}-{slug}-{index + 1}"
                group = (
                    "business-case"
                    if slug
                    in {
                        "fcerm-business-case-templates",
                        "the-green-book-templates-and-support-material",
                    }
                    else slug
                )
                if "independent-examiner" in slug or "cc16-charity" in slug:
                    group = "charity-accounts"
                if "procurement-policy-note" in slug:
                    group = "procurement-policy-notes"
                tasks.append(
                    {
                        "case_id": case_id,
                        "source": f"gov_uk_{ext}",
                        "format": ext,
                        "title": asset["title"],
                        "publication_url": pub["publication_url"],
                        "source_url": asset["url"],
                        "source_revision": pub["updated_at"],
                        "publisher": pub["publishers"],
                        "publication_content_id": pub["content_id"],
                        "path": f"eval/downloads/corpus/gov_uk_{ext}/{case_id}.{ext}",
                        "group_id": "gov-uk-family:" + group,
                        "split": split,
                        "pages_reported": asset["pages_reported"],
                        "license": "OGL-3.0-where-applicable",
                        "license_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
                        "attribution": (
                            "Contains public sector information published by "
                            f"{', '.join(pub['publishers'])}; "
                            f"Crown copyright where applicable. Source: {pub['publication_url']}. "
                            "OGL v3.0 subject to document-specific exclusions."
                        ),
                        "rights_status": (
                            "official_source; file_specific_ogl_exclusions_review_pending"
                        ),
                        "evaluation_ready": False,
                        "tags": ["government", "multi_page" if ext == "pdf" else "semantic_blocks"],
                    }
                )
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(acquire, tasks))
    write_json(ROOT / "eval/government-selection.json", records)
    print(f"Acquired {len(records)} government documents", flush=True)


if __name__ == "__main__":
    main()
