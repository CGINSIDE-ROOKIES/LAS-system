from doc_processor import parser
from doc_processor.las_types import DocumentState, IRGroup

from pathlib import Path
from typing import cast

parser_graph = parser.parser_graph

file_dirs_std_labor = list(Path("doc_samples/표준계약서모음(hwp-hwpx)").iterdir())
file_dirs_std_contracts = list(Path("doc_samples/(노동)표준근로계약서모음").iterdir())
file_dirs = file_dirs_std_labor + file_dirs_std_contracts

[print(f"{i}. {f.name}") for i, f in enumerate(file_dirs)]
sel = int(input("select: "))
file_path = file_dirs[sel]

result = parser_graph.invoke(
    input=DocumentState.from_file(Path(file_path)),
    config={"max_concurrency": 4}
)

with open(f"results/{file_path.name}_parser_res.txt", "w", encoding="utf-8") as f:
    for group in result["ir_groups"]:
        group = cast(IRGroup, group)
        for chunk in group.ir_chunks:
            text = chunk.text
            category = chunk.category
            f.write(f"category: {category} - {chunk.article_n}.{chunk.paragraph_n}\nchunk: {text}\n==========\n")