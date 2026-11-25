from freight_agents.tms_orders.mcp_server import order_rules


def test_the_order_rules_ship_with_the_package_and_carry_sources() -> None:
    rules = order_rules()
    assert len({p.doc_id for p in rules}) == 10
    assert all(p.source_url.startswith("https://") and p.read_on for p in rules)
