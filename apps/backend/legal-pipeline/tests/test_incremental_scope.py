from src.common.io_utils import _write_json, _write_jsonl
from src.pipeline.incremental_scope import resolve_incremental_scope


def test_resolve_incremental_scope_maps_changed_law_to_root_family(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"
    _write_json(
        normalized_dir / "근로기준법_시행령__parsed_law.json",
        {
            "law_name": "근로기준법 시행령",
            "law_id": "006860",
            "mst": "269394",
        },
    )
    _write_jsonl(
        tmp_path / "delta_events.jsonl",
        [
            {
                "event_id": "delta::law_changed::006860::all::20260324",
                "event_date": "20260324",
                "event_type": "law_changed",
                "law_id": "006860",
                "mst": "269394",
                "law_name": "근로기준법 시행령",
                "law_uid": "006860",
            },
            {
                "event_id": "delta::law_deleted::006860::all::20260324",
                "event_date": "20260324",
                "event_type": "law_deleted",
                "law_id": "006860",
                "mst": "269394",
                "law_name": "근로기준법 시행령",
                "law_uid": "006860",
            },
        ],
    )

    scope = {
        "outputs": [
            {
                "file_id": "01_current_law",
                "roots": {
                    "labor": ["근로기준법"],
                },
            }
        ]
    }

    resolved = resolve_incremental_scope(
        scope=scope,
        delta_events_path=tmp_path / "delta_events.jsonl",
        normalized_base_dir=tmp_path / "normalized" / "01_current_law",
    )

    assert resolved["changed_law_uids"] == ["006860"]
    assert resolved["deleted_law_uids"] == ["006860"]
    assert resolved["changed_root_law_names"] == ["근로기준법"]
    assert resolved["needs_related_refresh"] is True
    assert resolved["embed_collections"] == ["law_article", "legal_case"]


def test_resolve_incremental_scope_falls_back_to_law_name_when_ids_are_missing(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"
    _write_json(
        normalized_dir / "근로기준법_시행규칙__parsed_law.json",
        {
            "law_name": "근로기준법 시행규칙",
            "law_id": "006859",
            "mst": "269393",
        },
    )
    _write_jsonl(
        tmp_path / "delta_events.jsonl",
        [
            {
                "event_id": "delta::law_deleted::근로기준법_시행규칙::all::20260324",
                "event_date": "20260324",
                "event_type": "law_deleted",
                "law_id": "",
                "mst": "",
                "law_name": "근로기준법 시행규칙",
                "law_uid": "근로기준법_시행규칙",
            }
        ],
    )

    scope = {
        "outputs": [
            {
                "file_id": "01_current_law",
                "roots": {
                    "labor": ["근로기준법"],
                },
            }
        ]
    }

    resolved = resolve_incremental_scope(
        scope=scope,
        delta_events_path=tmp_path / "delta_events.jsonl",
        normalized_base_dir=tmp_path / "normalized" / "01_current_law",
    )

    assert resolved["deleted_law_uids"] == ["근로기준법_시행규칙"]
    assert resolved["changed_root_law_names"] == ["근로기준법"]
