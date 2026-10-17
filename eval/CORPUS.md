# Candidate corpus v1

All 120 primary documents are present and pass file integrity checks.
Local AI source reviews support development diagnostics. Independent human benchmark approval is not claimed.

| Source | Files | Development | Calibration | Holdout |
|---|---:|---:|---:|---:|
| cord_v2 | 30 | 18 | 6 | 6 |
| doclaynet | 35 | 21 | 7 | 7 |
| gov_uk_docx | 15 | 9 | 3 | 3 |
| gov_uk_pdf | 20 | 12 | 4 | 4 |
| synthetic | 20 | 12 | 4 | 4 |

Primary originals: **73.2 MiB**, excluding image counterparts, labels and cache.
Formats: 70 PDFs, 20 DOCX files and 30 PNG receipts. PDF originals total 611 pages.
DOCX physical pages are not assumed; semantic block IDs will be assigned during ingestion.

**Readiness:** 0 draft answer keys, 120 locally AI-reviewed answer keys, 0 unannotated cases, 0 human-reviewed evaluation-ready cases.
**Splits:** proposed 72/24/24 allocation; recorded groups do not cross splits. Final template/near-duplicate review remains pending.
**Rights:** dataset/publisher licence references recorded; external files remain local pending file-specific review.

A star marks one of the 24 selected development-preview cases. Each document has a local annotation work file.
See [setup and remaining work](README.md), [manifest](manifest.jsonl) and [machine validation](corpus-status.json).

## cord_v2

| Document | Split | Answers |
|---|---|---|
| [cord-v2-valid-0015](downloads/corpus/cord_v2/cord-v2-valid-0015.png) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-valid-0015.json) |
| [cord-v2-valid-0034](downloads/corpus/cord_v2/cord-v2-valid-0034.png) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-valid-0034.json) |
| [cord-v2-valid-0051](downloads/corpus/cord_v2/cord-v2-valid-0051.png) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-valid-0051.json) |
| [cord-v2-valid-0055](downloads/corpus/cord_v2/cord-v2-valid-0055.png) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-valid-0055.json) |
| [cord-v2-valid-0068](downloads/corpus/cord_v2/cord-v2-valid-0068.png) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-valid-0068.json) |
| [cord-v2-valid-0080](downloads/corpus/cord_v2/cord-v2-valid-0080.png) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-valid-0080.json) |
| * [cord-v2-train-0000](downloads/corpus/cord_v2/cord-v2-train-0000.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0000.json) |
| * [cord-v2-train-0011](downloads/corpus/cord_v2/cord-v2-train-0011.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0011.json) |
| * [cord-v2-train-0021](downloads/corpus/cord_v2/cord-v2-train-0021.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0021.json) |
| * [cord-v2-train-0031](downloads/corpus/cord_v2/cord-v2-train-0031.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0031.json) |
| * [cord-v2-train-0042](downloads/corpus/cord_v2/cord-v2-train-0042.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0042.json) |
| * [cord-v2-train-0052](downloads/corpus/cord_v2/cord-v2-train-0052.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0052.json) |
| [cord-v2-train-0062](downloads/corpus/cord_v2/cord-v2-train-0062.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0062.json) |
| [cord-v2-train-0073](downloads/corpus/cord_v2/cord-v2-train-0073.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0073.json) |
| [cord-v2-train-0083](downloads/corpus/cord_v2/cord-v2-train-0083.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0083.json) |
| [cord-v2-train-0093](downloads/corpus/cord_v2/cord-v2-train-0093.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0093.json) |
| [cord-v2-train-0103](downloads/corpus/cord_v2/cord-v2-train-0103.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0103.json) |
| [cord-v2-train-0113](downloads/corpus/cord_v2/cord-v2-train-0113.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0113.json) |
| [cord-v2-train-0124](downloads/corpus/cord_v2/cord-v2-train-0124.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0124.json) |
| [cord-v2-train-0135](downloads/corpus/cord_v2/cord-v2-train-0135.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0135.json) |
| [cord-v2-train-0146](downloads/corpus/cord_v2/cord-v2-train-0146.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0146.json) |
| [cord-v2-train-0157](downloads/corpus/cord_v2/cord-v2-train-0157.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0157.json) |
| [cord-v2-train-0171](downloads/corpus/cord_v2/cord-v2-train-0171.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0171.json) |
| [cord-v2-train-0190](downloads/corpus/cord_v2/cord-v2-train-0190.png) | development | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-train-0190.json) |
| [cord-v2-test-0004](downloads/corpus/cord_v2/cord-v2-test-0004.png) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-test-0004.json) |
| [cord-v2-test-0015](downloads/corpus/cord_v2/cord-v2-test-0015.png) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-test-0015.json) |
| [cord-v2-test-0019](downloads/corpus/cord_v2/cord-v2-test-0019.png) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-test-0019.json) |
| [cord-v2-test-0036](downloads/corpus/cord_v2/cord-v2-test-0036.png) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-test-0036.json) |
| [cord-v2-test-0053](downloads/corpus/cord_v2/cord-v2-test-0053.png) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-test-0053.json) |
| [cord-v2-test-0087](downloads/corpus/cord_v2/cord-v2-test-0087.png) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/cord-v2-test-0087.json) |

## doclaynet

| Document | Split | Answers |
|---|---|---|
| [doclaynet-2a05e96676dbbcbf2be7306848e664cb371f5bd33bea13c135b092460d6b6f96](downloads/corpus/doclaynet/2a05e96676dbbcbf2be7306848e664cb371f5bd33bea13c135b092460d6b6f96.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-2a05e96676dbbcbf2be7306848e664cb371f5bd33bea13c135b092460d6b6f96.json) |
| [doclaynet-4caba41d37f41e6b118999b38ec79bd426ccccff28b767d0c2f885d07b02f7b4](downloads/corpus/doclaynet/4caba41d37f41e6b118999b38ec79bd426ccccff28b767d0c2f885d07b02f7b4.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-4caba41d37f41e6b118999b38ec79bd426ccccff28b767d0c2f885d07b02f7b4.json) |
| [doclaynet-97eeaf54c762a91665ea2ef2c8e682b3c347a1e3bf655bbd6cc0b492ee1e8caa](downloads/corpus/doclaynet/97eeaf54c762a91665ea2ef2c8e682b3c347a1e3bf655bbd6cc0b492ee1e8caa.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-97eeaf54c762a91665ea2ef2c8e682b3c347a1e3bf655bbd6cc0b492ee1e8caa.json) |
| [doclaynet-9f28bda2e72a4bac52e369f6d2500250983f380cc739c89f4802a233a2ed2fa8](downloads/corpus/doclaynet/9f28bda2e72a4bac52e369f6d2500250983f380cc739c89f4802a233a2ed2fa8.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-9f28bda2e72a4bac52e369f6d2500250983f380cc739c89f4802a233a2ed2fa8.json) |
| [doclaynet-aae1d540b914501e607c842f48e42e43544ffafb4815f5ab924fbe650ae1b99a](downloads/corpus/doclaynet/aae1d540b914501e607c842f48e42e43544ffafb4815f5ab924fbe650ae1b99a.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-aae1d540b914501e607c842f48e42e43544ffafb4815f5ab924fbe650ae1b99a.json) |
| [doclaynet-b1ed3d6c989df88d37cb45f6d2ae80735406ef2cf4a5b971d6d6370c0c6ae1cb](downloads/corpus/doclaynet/b1ed3d6c989df88d37cb45f6d2ae80735406ef2cf4a5b971d6d6370c0c6ae1cb.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-b1ed3d6c989df88d37cb45f6d2ae80735406ef2cf4a5b971d6d6370c0c6ae1cb.json) |
| [doclaynet-f32d0078fb1e1246d08511af296e5c5c574f0635753ebc186198e5a05c09fcc4](downloads/corpus/doclaynet/f32d0078fb1e1246d08511af296e5c5c574f0635753ebc186198e5a05c09fcc4.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-f32d0078fb1e1246d08511af296e5c5c574f0635753ebc186198e5a05c09fcc4.json) |
| * [doclaynet-13c4fb35d4232697685e209c29e371fad5e97b2c1abda98e43501ea64f3ad832](downloads/corpus/doclaynet/13c4fb35d4232697685e209c29e371fad5e97b2c1abda98e43501ea64f3ad832.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-13c4fb35d4232697685e209c29e371fad5e97b2c1abda98e43501ea64f3ad832.json) |
| * [doclaynet-25356323c0795b4a7d1ed2198782a293f14098086faa496ccf72bc557cb50095](downloads/corpus/doclaynet/25356323c0795b4a7d1ed2198782a293f14098086faa496ccf72bc557cb50095.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-25356323c0795b4a7d1ed2198782a293f14098086faa496ccf72bc557cb50095.json) |
| * [doclaynet-2836fafcd10b4627641b153f90b38bf9ebdaee1b5bcf8c49fa51463fce1d6e15](downloads/corpus/doclaynet/2836fafcd10b4627641b153f90b38bf9ebdaee1b5bcf8c49fa51463fce1d6e15.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-2836fafcd10b4627641b153f90b38bf9ebdaee1b5bcf8c49fa51463fce1d6e15.json) |
| * [doclaynet-61b0210340f50bf991972b4e97c13bee9b8bf9b0589ec65425abea1d3a124823](downloads/corpus/doclaynet/61b0210340f50bf991972b4e97c13bee9b8bf9b0589ec65425abea1d3a124823.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-61b0210340f50bf991972b4e97c13bee9b8bf9b0589ec65425abea1d3a124823.json) |
| * [doclaynet-63139873f416bd817b76b631195fd6c199e462f6be37f758c6379d4c992322d2](downloads/corpus/doclaynet/63139873f416bd817b76b631195fd6c199e462f6be37f758c6379d4c992322d2.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-63139873f416bd817b76b631195fd6c199e462f6be37f758c6379d4c992322d2.json) |
| [doclaynet-66b1911ed638ccd11f4432d51839939b5b9fd7cca31c309788f7fec7d8cd7d16](downloads/corpus/doclaynet/66b1911ed638ccd11f4432d51839939b5b9fd7cca31c309788f7fec7d8cd7d16.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-66b1911ed638ccd11f4432d51839939b5b9fd7cca31c309788f7fec7d8cd7d16.json) |
| * [doclaynet-6fcfaf4ad4629226fb9f854bfd3034dc16ad2fc981573e671b86b60b95ae6dcd](downloads/corpus/doclaynet/6fcfaf4ad4629226fb9f854bfd3034dc16ad2fc981573e671b86b60b95ae6dcd.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-6fcfaf4ad4629226fb9f854bfd3034dc16ad2fc981573e671b86b60b95ae6dcd.json) |
| [doclaynet-7110562091cea104818be16f5062063cd6c0f645e94bf3fde2ec439deb5f783e](downloads/corpus/doclaynet/7110562091cea104818be16f5062063cd6c0f645e94bf3fde2ec439deb5f783e.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-7110562091cea104818be16f5062063cd6c0f645e94bf3fde2ec439deb5f783e.json) |
| [doclaynet-7f9785340e9726be8fbe9c3ed6c2e6294fe851350ccd66239e98eb67e6a60641](downloads/corpus/doclaynet/7f9785340e9726be8fbe9c3ed6c2e6294fe851350ccd66239e98eb67e6a60641.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-7f9785340e9726be8fbe9c3ed6c2e6294fe851350ccd66239e98eb67e6a60641.json) |
| [doclaynet-909c294f5c209b9550d557e616b7a865044bc82801714b45a27b7c4c939f5bed](downloads/corpus/doclaynet/909c294f5c209b9550d557e616b7a865044bc82801714b45a27b7c4c939f5bed.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-909c294f5c209b9550d557e616b7a865044bc82801714b45a27b7c4c939f5bed.json) |
| [doclaynet-992d2c81a9ebf9a58875857b2d0ec296c771e010c584f3c5f354eae9cedfa871](downloads/corpus/doclaynet/992d2c81a9ebf9a58875857b2d0ec296c771e010c584f3c5f354eae9cedfa871.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-992d2c81a9ebf9a58875857b2d0ec296c771e010c584f3c5f354eae9cedfa871.json) |
| [doclaynet-b8f752e8d4943a00ba7a21fa270be19d06a82786091503e8683ae982dc849f9c](downloads/corpus/doclaynet/b8f752e8d4943a00ba7a21fa270be19d06a82786091503e8683ae982dc849f9c.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-b8f752e8d4943a00ba7a21fa270be19d06a82786091503e8683ae982dc849f9c.json) |
| * [doclaynet-b9a3b0036494417e8895b2ec667082dfde2d30fdf4bc126b0f6fbb8a5667dc25](downloads/corpus/doclaynet/b9a3b0036494417e8895b2ec667082dfde2d30fdf4bc126b0f6fbb8a5667dc25.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-b9a3b0036494417e8895b2ec667082dfde2d30fdf4bc126b0f6fbb8a5667dc25.json) |
| [doclaynet-ba54fc6c20dd681db95ffeac62da4d2c193c3d07f5f6ae02800430dfa749fe19](downloads/corpus/doclaynet/ba54fc6c20dd681db95ffeac62da4d2c193c3d07f5f6ae02800430dfa749fe19.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-ba54fc6c20dd681db95ffeac62da4d2c193c3d07f5f6ae02800430dfa749fe19.json) |
| [doclaynet-bb1aa89ca15b657df1b5ef56e7c4e4971cab18e15d6db4f25b1dedf9545e79e8](downloads/corpus/doclaynet/bb1aa89ca15b657df1b5ef56e7c4e4971cab18e15d6db4f25b1dedf9545e79e8.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-bb1aa89ca15b657df1b5ef56e7c4e4971cab18e15d6db4f25b1dedf9545e79e8.json) |
| [doclaynet-c7a2ef74abef1eaa445b33a9c5bcea37e6659bf7837a40542feb6c333328f883](downloads/corpus/doclaynet/c7a2ef74abef1eaa445b33a9c5bcea37e6659bf7837a40542feb6c333328f883.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-c7a2ef74abef1eaa445b33a9c5bcea37e6659bf7837a40542feb6c333328f883.json) |
| [doclaynet-cb21b5c559236cde3d832cac278e34153c4732314e59cd47f2f63bea00362c50](downloads/corpus/doclaynet/cb21b5c559236cde3d832cac278e34153c4732314e59cd47f2f63bea00362c50.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-cb21b5c559236cde3d832cac278e34153c4732314e59cd47f2f63bea00362c50.json) |
| [doclaynet-d4d20c62fa4a93c0c5874b22301e2d06db3e2e412872b4876693b69768168e46](downloads/corpus/doclaynet/d4d20c62fa4a93c0c5874b22301e2d06db3e2e412872b4876693b69768168e46.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-d4d20c62fa4a93c0c5874b22301e2d06db3e2e412872b4876693b69768168e46.json) |
| [doclaynet-db309ed96f127be22bc17e3df8efefd48325ee68c84459d7a2232b795ddff07b](downloads/corpus/doclaynet/db309ed96f127be22bc17e3df8efefd48325ee68c84459d7a2232b795ddff07b.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-db309ed96f127be22bc17e3df8efefd48325ee68c84459d7a2232b795ddff07b.json) |
| [doclaynet-f09dc91ec20d409d9c65a4da8dfb255a3f5c7c16f7906a7c30ca992b396911db](downloads/corpus/doclaynet/f09dc91ec20d409d9c65a4da8dfb255a3f5c7c16f7906a7c30ca992b396911db.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-f09dc91ec20d409d9c65a4da8dfb255a3f5c7c16f7906a7c30ca992b396911db.json) |
| [doclaynet-f22b6b75085a206fb0c8149151a085da009b86680a46b31dd9cf57428206b6b7](downloads/corpus/doclaynet/f22b6b75085a206fb0c8149151a085da009b86680a46b31dd9cf57428206b6b7.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-f22b6b75085a206fb0c8149151a085da009b86680a46b31dd9cf57428206b6b7.json) |
| [doclaynet-2616a4734224e864b8f7b56e57125b073c02e633cdbcec312798aa763072344c](downloads/corpus/doclaynet/2616a4734224e864b8f7b56e57125b073c02e633cdbcec312798aa763072344c.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-2616a4734224e864b8f7b56e57125b073c02e633cdbcec312798aa763072344c.json) |
| [doclaynet-4c260c9b4c5c6fc09bbda28563e04994152b864350825313b1cb4a34d05a96ad](downloads/corpus/doclaynet/4c260c9b4c5c6fc09bbda28563e04994152b864350825313b1cb4a34d05a96ad.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-4c260c9b4c5c6fc09bbda28563e04994152b864350825313b1cb4a34d05a96ad.json) |
| [doclaynet-904b2eb7f637e02343986069b27b52d7691c74087d8993b579643d33bf88cbc4](downloads/corpus/doclaynet/904b2eb7f637e02343986069b27b52d7691c74087d8993b579643d33bf88cbc4.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-904b2eb7f637e02343986069b27b52d7691c74087d8993b579643d33bf88cbc4.json) |
| [doclaynet-99908d0419d9000658f35d77ec11a871c45e57740518cde1b608686f2587fb71](downloads/corpus/doclaynet/99908d0419d9000658f35d77ec11a871c45e57740518cde1b608686f2587fb71.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-99908d0419d9000658f35d77ec11a871c45e57740518cde1b608686f2587fb71.json) |
| [doclaynet-b0e42e073487f4c7151566469890327587c048352026f7af1ba941c4dfb2d94c](downloads/corpus/doclaynet/b0e42e073487f4c7151566469890327587c048352026f7af1ba941c4dfb2d94c.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-b0e42e073487f4c7151566469890327587c048352026f7af1ba941c4dfb2d94c.json) |
| [doclaynet-cfe482d4e853cf9227e2df9743eacbda6b5748e5f7c01ecf10eb0042284105ad](downloads/corpus/doclaynet/cfe482d4e853cf9227e2df9743eacbda6b5748e5f7c01ecf10eb0042284105ad.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-cfe482d4e853cf9227e2df9743eacbda6b5748e5f7c01ecf10eb0042284105ad.json) |
| [doclaynet-edd61485fd5d352af5e5b303eac0efa0b107c23f74765937673ad777be5599a6](downloads/corpus/doclaynet/edd61485fd5d352af5e5b303eac0efa0b107c23f74765937673ad777be5599a6.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/doclaynet-edd61485fd5d352af5e5b303eac0efa0b107c23f74765937673ad777be5599a6.json) |

## gov_uk_docx

| Document | Split | Answers |
|---|---|---|
| [Financial remedy summary of case: Form ES1 - for Microsoft Word](downloads/corpus/gov_uk_docx/gov-uk-docx-financial-remedy-summary-of-case-form-es1-1.docx) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-financial-remedy-summary-of-case-form-es1-1.json) |
| [Independent examiner's report template for Receipts & Payments accounts](downloads/corpus/gov_uk_docx/gov-uk-docx-independent-examiners-report-template-for-receipts-and-payments-accounts-1.docx) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-independent-examiners-report-template-for-receipts-and-payments-accounts-1.json) |
| [The right to request flexible working: application form template (.docx)](downloads/corpus/gov_uk_docx/gov-uk-docx-the-right-to-request-flexible-working-form-1.docx) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-the-right-to-request-flexible-working-form-1.json) |
| * [Bribery and corruption assessment template](downloads/corpus/gov_uk_docx/gov-uk-docx-bribery-and-corruption-assessment-template-1.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-bribery-and-corruption-assessment-template-1.json) |
| * [Carriage of dangerous goods annual report template](downloads/corpus/gov_uk_docx/gov-uk-docx-carriage-of-dangerous-goods-annual-report-template-1.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-carriage-of-dangerous-goods-annual-report-template-1.json) |
| * [Explanatory Memorandum Template 2025-01](downloads/corpus/gov_uk_docx/gov-uk-docx-explanatory-memorandum-template-and-guidance-1.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-explanatory-memorandum-template-and-guidance-1.json) |
| [Report template: end of year](downloads/corpus/gov_uk_docx/gov-uk-docx-guidance-for-seed-sourcing-grant-recipients-1.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-guidance-for-seed-sourcing-grant-recipients-1.json) |
| [Regulatory impact assessment template (2023 reforms)](downloads/corpus/gov_uk_docx/gov-uk-docx-impact-assessment-template-for-government-policies-1.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-impact-assessment-template-for-government-policies-1.json) |
| [Options assessment template (2023 reforms)](downloads/corpus/gov_uk_docx/gov-uk-docx-impact-assessment-template-for-government-policies-2.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-impact-assessment-template-for-government-policies-2.json) |
| [Debt recovery, returning reclaimed grants and referring outstanding debts to the department: guid...](downloads/corpus/gov_uk_docx/gov-uk-docx-local-restrictions-support-grants-lrsg-and-additional-restrictions-grant-arg-guidance-for-local-authorities-1.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-local-restrictions-support-grants-lrsg-and-additional-restrictions-grant-arg-guidance-for-local-authorities-1.json) |
| [Template Delegated Authority Letter – Departments](downloads/corpus/gov_uk_docx/gov-uk-docx-managing-public-money-1.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-managing-public-money-1.json) |
| [Template framework document: Non-departmental public bodies](downloads/corpus/gov_uk_docx/gov-uk-docx-managing-public-money-framework-documents-1.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-managing-public-money-framework-documents-1.json) |
| [Business case template - supported change](downloads/corpus/gov_uk_docx/gov-uk-docx-fcerm-business-case-templates-3.docx) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-fcerm-business-case-templates-3.json) |
| [Applicant's response template](downloads/corpus/gov_uk_docx/gov-uk-docx-response-template-for-applicants-1.docx) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-response-template-for-applicants-1.json) |
| [Template for medium-cost risk Business Justification](downloads/corpus/gov_uk_docx/gov-uk-docx-the-green-book-templates-and-support-material-1.docx) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-docx-the-green-book-templates-and-support-material-1.json) |

## gov_uk_pdf

| Document | Split | Answers |
|---|---|---|
| [FCDO Services Annual Report and Accounts 2024 to 2025](downloads/corpus/gov_uk_pdf/gov-uk-pdf-fcdo-services-annual-report-and-accounts-2024-to-2025-1.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-fcdo-services-annual-report-and-accounts-2024-to-2025-1.json) |
| [Completion notes for the receipts and payments accounts pack (CC16b)](downloads/corpus/gov_uk_pdf/gov-uk-pdf-receipts-and-payments-accounts-cc16-charity-accounting-template-1.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-receipts-and-payments-accounts-cc16-charity-accounting-template-1.json) |
| [Template holding register for cattle](downloads/corpus/gov_uk_pdf/gov-uk-pdf-template-holding-register-for-cattle-keepers-1.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-template-holding-register-for-cattle-keepers-1.json) |
| [Warm Homes: Local Grant - policy guidance (updated July 2026)](downloads/corpus/gov_uk_pdf/gov-uk-pdf-warm-homes-local-grant-1.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-warm-homes-local-grant-1.json) |
| * [Agroforestry plan template](downloads/corpus/gov_uk_pdf/gov-uk-pdf-agroforestry-plan-pa4-complete-your-templates-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-agroforestry-plan-pa4-complete-your-templates-1.json) |
| * [Part B10 application form](downloads/corpus/gov_uk_pdf/gov-uk-pdf-application-for-an-environmental-permit-part-b10-flood-risk-activities-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-application-for-an-environmental-permit-part-b10-flood-risk-activities-1.json) |
| * [Application form: EX160](downloads/corpus/gov_uk_pdf/gov-uk-pdf-apply-for-help-with-court-and-tribunal-fees-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-apply-for-help-with-court-and-tribunal-fees-1.json) |
| * [Umbrella Climate Change Agreement template](downloads/corpus/gov_uk_pdf/gov-uk-pdf-climate-change-agreements-scheme-templates-for-umbrella-and-underlying-agreements-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-climate-change-agreements-scheme-templates-for-umbrella-and-underlying-agreements-1.json) |
| [Fairtrade Foundation informal guidance](downloads/corpus/gov_uk_pdf/gov-uk-pdf-cma-informal-guidance-fairtrade-environmental-sustainability-agreement-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-cma-informal-guidance-fairtrade-environmental-sustainability-agreement-1.json) |
| [Defra's social and environmental guidance to Ofwat:2nd ed - Full Text](downloads/corpus/gov_uk_pdf/gov-uk-pdf-defras-draft-social-and-environmental-guidance-to-ofwat-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-defras-draft-social-and-environmental-guidance-to-ofwat-1.json) |
| [Disabled Facilities Grant (DFG) delivery: Guidance for local authorities in England](downloads/corpus/gov_uk_pdf/gov-uk-pdf-disabled-facilities-grant-dfg-delivery-guidance-for-local-authorities-in-england-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-disabled-facilities-grant-dfg-delivery-guidance-for-local-authorities-in-england-1.json) |
| [GCE Subject Level Guidance for Environmental Science](downloads/corpus/gov_uk_pdf/gov-uk-pdf-gce-subject-level-guidance-for-environmental-science-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-gce-subject-level-guidance-for-environmental-science-1.json) |
| [Application to the Secretary of State for Energy & Climate Change  from 1 October 2013 for the gr...](downloads/corpus/gov_uk_pdf/gov-uk-pdf-granting-a-necessary-compulsory-electricity-wayleave-guidance-for-applicants-and-landowner-and-or-occupiers-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-granting-a-necessary-compulsory-electricity-wayleave-guidance-for-applicants-and-landowner-and-or-occupiers-1.json) |
| [Humanitarian protection in asylum claims lodged on or after 28 June 2022](downloads/corpus/gov_uk_pdf/gov-uk-pdf-humanitarian-protection-instruction-2.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-humanitarian-protection-instruction-2.json) |
| [Procurement Policy Note: Measures to Promote Tax Compliance](downloads/corpus/gov_uk_pdf/gov-uk-pdf-procurement-policy-note-0613-promoting-tax-compliance-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-procurement-policy-note-0613-promoting-tax-compliance-1.json) |
| [Taking account of bidders' past performance](downloads/corpus/gov_uk_pdf/gov-uk-pdf-procurement-policy-note-09-12-taking-account-of-bidders-past-performance-1.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-procurement-policy-note-09-12-taking-account-of-bidders-past-performance-1.json) |
| [V62](downloads/corpus/gov_uk_pdf/gov-uk-pdf-application-for-a-vehicle-registration-certificate-1.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-application-for-a-vehicle-registration-certificate-1.json) |
| [Sovereign Grant Act 2011 guidance](downloads/corpus/gov_uk_pdf/gov-uk-pdf-sovereign-grant-act-2011-guidance-1.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-sovereign-grant-act-2011-guidance-1.json) |
| [The National Gallery Annual Report and Accounts 2024 to 2025](downloads/corpus/gov_uk_pdf/gov-uk-pdf-the-national-gallery-annual-report-and-accounts-2024-to-2025-1.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-the-national-gallery-annual-report-and-accounts-2024-to-2025-1.json) |
| [Winter Fuel Payment application form](downloads/corpus/gov_uk_pdf/gov-uk-pdf-winter-fuel-payment-claim-form-1.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/gov-uk-pdf-winter-fuel-payment-claim-form-1.json) |

## synthetic

| Document | Split | Answers |
|---|---|---|
| [synthetic-docx-04](downloads/corpus/synthetic/synthetic-docx-04.docx) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-docx-04.json) |
| [synthetic-mixed-04](downloads/corpus/synthetic/synthetic-mixed-04.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-mixed-04.json) |
| [synthetic-native-04](downloads/corpus/synthetic/synthetic-native-04.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-native-04.json) |
| [synthetic-scan-04](downloads/corpus/synthetic/synthetic-scan-04.pdf) | calibration | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-scan-04.json) |
| * [synthetic-docx-01](downloads/corpus/synthetic/synthetic-docx-01.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-docx-01.json) |
| [synthetic-docx-02](downloads/corpus/synthetic/synthetic-docx-02.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-docx-02.json) |
| [synthetic-docx-03](downloads/corpus/synthetic/synthetic-docx-03.docx) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-docx-03.json) |
| * [synthetic-mixed-01](downloads/corpus/synthetic/synthetic-mixed-01.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-mixed-01.json) |
| [synthetic-mixed-02](downloads/corpus/synthetic/synthetic-mixed-02.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-mixed-02.json) |
| [synthetic-mixed-03](downloads/corpus/synthetic/synthetic-mixed-03.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-mixed-03.json) |
| * [synthetic-native-01](downloads/corpus/synthetic/synthetic-native-01.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-native-01.json) |
| [synthetic-native-02](downloads/corpus/synthetic/synthetic-native-02.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-native-02.json) |
| [synthetic-native-03](downloads/corpus/synthetic/synthetic-native-03.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-native-03.json) |
| * [synthetic-scan-01](downloads/corpus/synthetic/synthetic-scan-01.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-scan-01.json) |
| [synthetic-scan-02](downloads/corpus/synthetic/synthetic-scan-02.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-scan-02.json) |
| [synthetic-scan-03](downloads/corpus/synthetic/synthetic-scan-03.pdf) | development | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-scan-03.json) |
| [synthetic-docx-05](downloads/corpus/synthetic/synthetic-docx-05.docx) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-docx-05.json) |
| [synthetic-mixed-05](downloads/corpus/synthetic/synthetic-mixed-05.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-mixed-05.json) |
| [synthetic-native-05](downloads/corpus/synthetic/synthetic-native-05.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-native-05.json) |
| [synthetic-scan-05](downloads/corpus/synthetic/synthetic-scan-05.pdf) | holdout | [ai_reviewed](downloads/corpus/ai-reviewed/synthetic-scan-05.json) |
