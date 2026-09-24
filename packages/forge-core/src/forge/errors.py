"""Domain errors surfaced by the Forge CLI and API."""


class ForgeError(Exception):
    """Base class for expected Forge failures."""


class JsonFileError(ForgeError):
    """A JSON input could not be read or decoded."""


class ResumeValidationError(ForgeError):
    """Canonical resume data does not conform to its schema."""


class DuplicateResumeIdError(ResumeValidationError):
    """Canonical resume data contains a repeated stable ID."""


class BindingError(ForgeError):
    """A template binding is invalid or cannot be resolved."""


class OperationError(ForgeError):
    """An AI-authored semantic resume operation is invalid."""


class ProviderError(ForgeError):
    """An external AI provider failed or returned an invalid result."""


class TailoringError(ForgeError):
    """The end-to-end tailoring workflow could not complete."""


class ContextStoreError(ForgeError):
    """The SQLite candidate-context index could not be read or updated."""


class UsageStoreError(ForgeError):
    """The SQLite LLM request/cost ledger could not be read or updated."""


class DocxError(ForgeError):
    """A DOCX archive or WordprocessingML part is invalid."""


class PDFConversionError(ForgeError):
    """A rendered DOCX could not be converted into a valid PDF."""


class MissingTemplateBindingError(BindingError):
    """One or more template SDTs have no resolved value."""

    def __init__(self, tags):
        self.tags = tuple(sorted(set(tags)))
        label = "Missing template binding" if len(self.tags) == 1 else "Missing template bindings"
        details = "\n".join(f"- {tag}" for tag in self.tags)
        super().__init__(f"{label}:\n{details}")
