=============
ME:
so the current editing API requires it's own type. seems clean but the problem is:
since all the intermediate object needs to be the specified type and also requires the document path every time, it seems to
lack flexibility in some ways. such as:
- loading preprocessed DocIRs - since we're loading via Path, info is lost + have to parse every time?
- in situations such as dealing with web uploads

also now that I look at it, if you manage to fix the limitations above I think we can just generally apply that to DocIR.
can that be done (I realized that the types are fundamentally different though hmmmmm)

I do hope to intergrate the editing plane/API to the native DocIR... just in case, the DocIR is in /home/maxjo/Work/
document-processor

=============
AGENT:
Yes, this can be done. The current limitation is mostly in our API layer, not in DocIR itself.

DocIR already supports Path | bytes | BinaryIO and already carries source_path / source_doc_type in /home/maxjo/Work/
document-processor/src/document_processor/models.py:179 and /home/maxjo/Work/document-processor/src/document_processor/
models.py:201. The real path-only assumptions are in apps/backend/doc_processor/src/doc_processor/api.py:117 and apps/
backend/doc_processor/src/doc_processor/edit_engine.py:667.

Plan:

1. Stop making the public API source_path-only. Accept DocIR | path | bytes | BinaryIO on the Python side, and a structured
    DocumentInput on the tool side.
2. Introduce a wrapper type, not a DocIR replacement. Something like EditableDocument or DocumentHandle with:
    - doc_ir
    - native_source as path | bytes | None
    - source_doc_type
    - source_name
    - doc_id
3. Make all read/validate/edit operations work from resolved DocIR, not by reparsing a path every time.
    - get_document_context
    - list_editable_targets
    - validate_document_edits
    - render_review_html
4. Split apply into two capabilities behind one surface:
    - if only DocIR is available: apply in-memory and return updated DocIR
    - if native source is available: also support native write-back
5. Move source normalization closer to document-processor, because it already has the right primitives like /home/maxjo/Work/
    document-processor/src/document_processor/io_utils.py:52 and /home/maxjo/Work/document-processor/src/document_processor/
    io_utils.py:119.
6. For web uploads, support bytes-backed native editing by storing upload bytes in the wrapper instead of forcing a temp path
    at the API boundary.
7. For tool calls, add an optional handle-based flow so the model does not need to resend or reparse the full document every
    call.

What I would not do:

- I would not make raw DocIR itself responsible for native round-trip state. DocIR is structural IR; native source/provenance
is a different concern.
- I would not merge the edit DTOs into DocIR metadata.

One decision I need from you before implementation: should the tool/API be stateful with document handles, or stateless where
the caller resends bytes/DocIR each call? That choice changes the design a lot.

=============
USER:
stateless for the future DocIT editor public API

though in the actual implementation (langgraph) it should be used as a stateful state
