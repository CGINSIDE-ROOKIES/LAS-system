from hwpx import HwpxDocument
from hwpx.oxml import HwpxOxmlRun


def get_run_by_id(doc: HwpxDocument, chunk_id: str) -> HwpxOxmlRun:
    """
    Resolve a chunk ID like ``'s1.p44.r2'`` to its :class:`HwpxOxmlRun`.

    IDs use 1-based indexing; indices are converted to 0-based internally.

    Raises:
        ValueError: For table chunk IDs (not supported) or out-of-range indices.
    """
    if ".tbl" in chunk_id:
        raise ValueError(f"Table run IDs not supported yet: {chunk_id}")

    parts = chunk_id.split(".")
    s = int(parts[0][1:]) - 1
    p = int(parts[1][1:]) - 1
    r = int(parts[2][1:]) - 1

    return doc.sections[s].paragraphs[p].runs[r]
