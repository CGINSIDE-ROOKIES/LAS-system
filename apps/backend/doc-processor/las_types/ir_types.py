from pydantic import BaseModel, Field


class RunSpan(BaseModel):
    """Character range of one IR chunk within IRGroup.formatted_str."""
    start: int
    end: int
    chunk_id: str  # e.g. "s1.p44.r2"


class IRChunk(BaseModel):
    raw_text: str = ""
    markdown_text: str = ""
    category: str = "uncategorized"
    article_n: list[str] = Field(default_factory=list)
    paragraph_n: list[str] = Field(default_factory=list)
    splits: list[tuple[int, int]] = Field(default_factory=list)


class IRGroup(BaseModel):
    formatted_str: str = ""
    article_n: str = "-1"
    ir_chunk_ids: list[str] = Field(default_factory=list)
    ir_chunks: list[IRChunk] = Field(default_factory=list)
    ir_join: list[int] = Field(default_factory=list)   # start of each chunk in formatted_str
    ir_trim: tuple[int, int] = (0, 0)
    category_spans: list[tuple[int, int, str]] = Field(default_factory=list)
    # Each entry: (start, end, category) — character range in formatted_str.
    # Consecutive same-category chunks are merged.
    # Example: [(0, 42, 'unk'), (42, 180, 'unk-table'), (180, 210, 'unk')]

    def run_spans(self) -> list[RunSpan]:
        """Return character ranges of each non-table chunk in formatted_str."""
        spans: list[RunSpan] = []
        for i, chunk_id in enumerate(self.ir_chunk_ids):
            if ".tbl" in chunk_id:
                continue
            start = self.ir_join[i]
            end = self.ir_join[i + 1] if i + 1 < len(self.ir_join) else len(self.formatted_str)
            spans.append(RunSpan(start=start, end=end, chunk_id=chunk_id))
        return spans

