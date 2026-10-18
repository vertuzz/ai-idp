"""Canonical spreadsheet media types shared by admission and document adapters."""

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSM_MIME = "application/vnd.ms-excel.sheet.macroEnabled.12"
XLSB_MIME = "application/vnd.ms-excel.sheet.binary.macroEnabled.12"
SPREADSHEET_TYPES = {XLSX_MIME, XLSM_MIME, XLSB_MIME, "application/vnd.ms-excel"}
