from src.pipeline.law_pipeline import select_family_law_refs_from_search


def test_family_selection_basic():
    current_law_list_payload = {
        "LawSearch": {
            "law": [
                {
                    "법령명한글": "근로기준법",
                    "법령약칭명": "",
                    "법령구분명": "법률",
                    "법령ID": "001",
                    "법령일련번호": "mst001",
                    "시행일자": "20240101",
                },
                {
                    "법령명한글": "근로기준법 시행령",
                    "법령약칭명": "",
                    "법령구분명": "대통령령",
                    "법령ID": "002",
                    "법령일련번호": "mst002",
                    "시행일자": "20240101",
                },
                {
                    "법령명한글": "근로기준법 시행규칙",
                    "법령약칭명": "",
                    "법령구분명": "부령",
                    "법령ID": "003",
                    "법령일련번호": "mst003",
                    "시행일자": "20240101",
                },
                {
                    "법령명한글": "최저임금법",
                    "법령약칭명": "",
                    "법령구분명": "법률",
                    "법령ID": "004",
                    "법령일련번호": "mst004",
                    "시행일자": "20240101",
                },
            ]
        }
    }

    allowed_levels = {"법", "시행령", "시행규칙"}

    result = select_family_law_refs_from_search(
        current_law_list_payload=current_law_list_payload,
        root_law_name="근로기준법",
        allowed_levels=allowed_levels,
    )

    names = [item["law_name"] for item in result]

    assert "근로기준법" in names
    assert "근로기준법 시행령" in names
    assert "근로기준법 시행규칙" in names
    assert "최저임금법" not in names


def test_family_selection_uses_system_diagram_exact_descendants():
    current_law_list_payload = {
        "LawSearch": {
            "law": [
                {
                    "법령명한글": "근로기준법",
                    "법령구분명": "법률",
                    "법령ID": "001",
                    "법령일련번호": "mst001",
                    "시행일자": "20240101",
                },
                {
                    "법령명한글": "근로기준법 시행령",
                    "법령구분명": "대통령령",
                    "법령ID": "002",
                    "법령일련번호": "mst002",
                    "시행일자": "20240101",
                },
                {
                    "법령명한글": "근로감독관규정",
                    "법령구분명": "부령",
                    "법령ID": "003",
                    "법령일련번호": "mst003",
                    "시행일자": "20240101",
                },
            ]
        }
    }

    system_diagram_detail = {
        "법령체계도": {
            "법령": {
                "법령명": "근로기준법",
                "법령ID": "001",
                "하위법령": [
                    {
                        "법령명": "근로기준법 시행령",
                        "법령ID": "002",
                        "법령구분명": "대통령령",
                    },
                    {
                        "법령명": "근로감독관규정",
                        "법령ID": "003",
                        "법령구분명": "부령",
                    },
                ],
            }
        }
    }

    result = select_family_law_refs_from_search(
        current_law_list_payload=current_law_list_payload,
        root_law_name="근로기준법",
        allowed_levels={"법", "시행령", "시행규칙"},
        system_diagram_detail=system_diagram_detail,
        include_descendants_from_system_diagram=True,
    )

    names = [item["law_name"] for item in result]

    assert "근로기준법" in names
    assert "근로기준법 시행령" in names
    assert "근로감독관규정" in names
