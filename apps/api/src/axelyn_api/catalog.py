"""Public service definitions exposed through the API."""

SERVICES = (
    {
        "id": "resume-tailoring",
        "name": "Resume tailoring",
        "summary": (
            "A focused resume shaped around one role while keeping every claim "
            "grounded in your real experience."
        ),
        "deliverables": (
            "Role-aligned resume",
            "Editable DOCX",
            "Ready-to-send PDF",
            "Change and keyword audit",
        ),
    },
    {
        "id": "application-kit",
        "name": "Complete application kit",
        "summary": (
            "A coordinated resume and cover letter for one opportunity, built from "
            "the same verified source material."
        ),
        "deliverables": (
            "Role-aligned resume",
            "Tailored cover letter",
            "DOCX and PDF files",
            "Evidence and keyword audit",
        ),
    },
    {
        "id": "resume-system",
        "name": "Reusable resume system",
        "summary": (
            "A structured source profile and Word template that make future "
            "applications faster without losing your preferred design."
        ),
        "deliverables": (
            "Structured career profile",
            "Tagged Word template",
            "Reusable content library",
            "One launch-ready application kit",
        ),
    },
)

SERVICE_IDS = frozenset(service["id"] for service in SERVICES)
