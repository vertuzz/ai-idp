from ai_idp.application.services.verification_parts import value_parts


def test_large_scalar_collection_partitions_without_recursive_tail_growth():
    values = list(range(50_000))
    parts = value_parts({"outer": {"items": values}})
    assert [item for part in parts for item in part["outer"]["items"]] == values
    assert all(len(part["outer"]["items"]) <= 25 for part in parts)
