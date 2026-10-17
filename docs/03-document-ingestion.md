# 03 — Document Ingestion and Normalization

## Ingestion workflow

- Stream multipart uploads to a restricted temporary file, compute SHA-256, check actual file type and enforce a configured size limit.
- Persist original bytes in local DocumentBlobStore with a generated ID, not a user-supplied filename as a path.
- Save normalized metadata in PostgreSQL, then prepare units asynchronously if needed.
- Reuse immutable prepared units when processing the same document with a different extraction schema.
- Every unit includes origin metadata and a stable source reference.

## Canonical DocumentUnit

~~~json
{
  "unit_id": "unit_000017",
  "document_id": "doc_123",
  "ordinal": 17,
  "kind": "pdf_page",
  "source_locator": {"page_number": 17},
  "native_text_ref": "artifacts/text/unit_000017.txt",
  "image_ref": "artifacts/render/unit_000017.webp",
  "metadata": {
    "width_points": 612,
    "height_points": 792,
    "image_count": 3,
    "text_character_count": 2438
  }
}
~~~

The example shows references, not inline raw document content. Optional fields are omitted when not available. Units can also be docx_block or image_frame.

## PDF adapter — PyMuPDF

- Read page count, page dimensions, text and text blocks when directly available.
- Render a preview image for each page at configurable resolution; preserve original page ID/number.
- Store text and image as separate derived artifacts, enabling decision engines to see either or both.
- Do not interpret missing/short native text as a deterministic decision to run an OCR or vision path.
- Expose PDF text as imperfect evidence: extraction may lose reading order, table associations, and text hidden in images.
- Support configurable lazy rendering/caching if full upfront rendering becomes expensive.

## DOCX adapter — Mammoth (no LibreOffice)

Mammoth converts the DOCX to **semantic HTML**, not a pixel-accurate Word layout. Extract headings, paragraphs, tables, and embedded image relationships; create coherent semantic blocks with stable IDs.

- Split into bounded logical units at headings, table boundaries, or size limits, carrying brief adjacent context for continuity.
- Preserve HTML/table structure where useful; sanitize HTML when rendering it or exposing it to consumers.
- Track embedded images as referenced artifacts; attach them to relevant blocks where possible.
- A block's `image_refs` contains every embedded image, with `image_ref` retained as the primary-image compatibility field. All images are loaded into model input; multi-image blocks cite the semantic block rather than falsely attributing the whole block to its first image. Existing stored DOCX units recover their image list from saved metadata.
- A DOCX block does not have a reliable physical page number. Return block IDs/heading positions instead.
- Some information can depend on styles/headers/footers/drawings that semantic conversion does not preserve. Surface conversion warnings, do not silently claim perfect fidelity.
- If later evaluation demands exact page layout, an optional renderer can be introduced as a new adapter, without imposing LibreOffice on the MVP.

## Image adapter

Support PNG, JPEG, and TIFF. A single image is one unit; each TIFF frame gets a stable frame locator. Store dimensions and image artifact references. No native text is assumed.

## Safe boundaries

Suggested initial *configurable* defaults:

| Setting | Initial default |
|---|---:|
| Upload size | 200 MiB |
| PDF pages | 1,000 |
| DOCX semantic blocks | 1,000 |
| Total expanded input bytes | 1 GiB |
| Maximum image pixels per frame | 40 million |
| Maximum file processing runtime | 10 minutes |

Reject archive bombs, excessive decompression, malformed input and unsupported types. Isolate untrusted document decoding, apply runtime/memory caps, and prevent macro execution. DOCX ZIP processing requires explicit expanded-size and entry-count limits. Use no remote URLs embedded in documents. Avoid path traversal and unsanitized user filenames.

## Provenance design

PDF: page number and optional normalized or original coordinates. DOCX: semantic block ID, heading path and optional local offset. Images: frame index and optional coordinates. One extracted field may reference multiple units.

The normalized representation makes no claim that the source can always be converted to visually faithful pages. Every downstream algorithm must use source locators appropriate to its format.
