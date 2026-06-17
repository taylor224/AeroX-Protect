from server.util.snowflake import SEED_ID_MAX, SnowflakeGenerator, generate_snowflake_id


def test_ids_unique_and_monotonic():
    ids = [generate_snowflake_id() for _ in range(5000)]
    assert len(set(ids)) == 5000          # no duplicates
    assert ids == sorted(ids)             # strictly increasing within a process


def test_ids_above_seed_range():
    assert generate_snowflake_id() > SEED_ID_MAX


def test_instances_never_collide():
    g1 = SnowflakeGenerator(1)
    g2 = SnowflakeGenerator(2)
    a = {g1.next_id() for _ in range(2000)}
    b = {g2.next_id() for _ in range(2000)}
    assert a.isdisjoint(b)


def test_rejects_out_of_range_instance():
    import pytest

    with pytest.raises(ValueError):
        SnowflakeGenerator(99999)
