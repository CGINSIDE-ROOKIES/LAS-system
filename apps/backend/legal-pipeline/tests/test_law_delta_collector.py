import json
from pathlib import Path

from src.collector.law_delta_collector import collect_daily_law_delta


def _registry() -> dict:
    return {
        "runtime": {
            "api_base_url": "http://example.test",
            "auth_param": "OC",
            "preferred_type": "JSON",
            "timeout_sec": 30,
        },
        "endpoints": {
            "law_change_daily": {
                "enabled": True,
                "path": "/lawSearch.do",
                "target": "lsHstInf",
                "required_params": ["OC", "target", "type", "regDt"],
                "default_params": {"display": 100, "page": 1},
            },
            "law_article_change_daily": {
                "enabled": True,
                "path": "/lawSearch.do",
                "target": "lsJoHstInf",
                "required_params": ["OC", "target", "type"],
                "one_of_param_groups": [["regDt"]],
                "default_params": {"page": 1},
            },
            "law_delete_daily": {
                "enabled": True,
                "path": "/lawSearch.do",
                "target": "delHst",
                "required_params": ["OC", "target", "type"],
                "optional_params": ["delDt"],
                "default_params": {"display": 100, "page": 1, "knd": 1},
            },
        },
    }


def test_collect_daily_law_delta_writes_events_and_queue(tmp_path, monkeypatch):
    fixture_dir = Path(__file__).parent / "fixtures"
    payload_by_target = {
        "lsHstInf": json.loads((fixture_dir / "law_change_daily.json").read_text(encoding="utf-8")),
        "lsJoHstInf": json.loads((fixture_dir / "law_article_change_daily.json").read_text(encoding="utf-8")),
        "delHst": json.loads((fixture_dir / "law_delete_daily.json").read_text(encoding="utf-8")),
    }

    def fake_execute_api_request(request):
        payload = payload_by_target[request.params["target"]]
        return {
            "parsed": payload,
            "url": f"http://example.test/{request.params['target']}",
            "format": "json",
            "content_type": "application/json",
        }

    monkeypatch.setattr("src.collector.law_delta_collector.execute_api_request", fake_execute_api_request)

    summary = collect_daily_law_delta(
        registry=_registry(),
        oc="test-oc",
        reg_dt="20260324",
        base_dir=tmp_path,
    )

    assert summary["event_count"] == 3
    assert summary["changed_law_count"] == 1

    delta_events = [
        json.loads(line)
        for line in (tmp_path / "delta" / "20260324" / "delta_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {item["event_type"] for item in delta_events} == {"law_changed", "article_changed", "law_deleted"}
    assert next(item for item in delta_events if item["event_type"] == "article_changed")["article_key"] == "1"

    changed_queue = [
        json.loads(line)
        for line in (tmp_path / "delta" / "20260324" / "changed_law_queue.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(changed_queue) == 1
    assert changed_queue[0]["law_uid"] == "001"
    assert changed_queue[0]["event_types"] == ["article_changed", "law_changed", "law_deleted"]
