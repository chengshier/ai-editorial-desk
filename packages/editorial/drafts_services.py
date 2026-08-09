"""M4-D public service surface.

Implementation is split by artifact responsibility while this module keeps stable imports
for API/tests and future M5 consumers.
"""

from packages.editorial.drafts_artifacts import EditorialPackService, EventCardService
from packages.editorial.drafts_generation import (
    DraftGenerationOutcome,
    DraftService,
    HumanDraftReference,
    StructuredGateway,
)
from packages.editorial.drafts_markdown import EditorialMarkdownExporter

__all__ = [
    "DraftGenerationOutcome",
    "DraftService",
    "EditorialMarkdownExporter",
    "EditorialPackService",
    "EventCardService",
    "HumanDraftReference",
    "StructuredGateway",
]
