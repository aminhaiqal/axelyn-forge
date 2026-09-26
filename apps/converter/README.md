# Axelyn Forge converter

This private FastAPI service converts uploaded PDFs into editable DOCX sources and generated DOCX files into PDFs with headless LibreOffice Writer. It is reachable only on the internal Compose network and has no public gateway route.

Each conversion uses a temporary workspace and isolated LibreOffice profile. The core conversion engine validates DOCX input, requires a structurally valid PDF result, and atomically publishes the output inside that workspace. Service concurrency defaults to one conversion to bound memory use.

Run it locally after installing LibreOffice:

```bash
forge-converter
```

The API calls `POST /v1/convert/pdf-to-docx` and `POST /v1/convert/docx-to-pdf` as multipart form data. `GET /healthz` reports unhealthy when the `soffice` executable is unavailable.
