"""文档无障碍证据审计"""

from . import reading_order, table_headers, form_controls, image_alternatives, text_language, navigation_links
from .contract import Row

PIPELINES = {
    "reading-order": reading_order.build_facts,
    "table-headers": table_headers.build_facts,
    "form-controls": form_controls.build_facts,
    "image-alternatives": image_alternatives.build_facts,
    "text-language": text_language.build_facts,
    "navigation-links": navigation_links.build_facts,
}


def process(pipeline: str, data: Row) -> list[Row]:
    """Validate and transform an independent input dataset into keyed facts."""
    if pipeline not in PIPELINES:
        raise ValueError(f"unknown pipeline: {pipeline}")
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object")
    return PIPELINES[pipeline](data)
