import spork.pds as pds


def test_namespaced_pds_api_exposes_types_factories_and_constants():
    assert pds.vec() is pds.EMPTY_VECTOR
    assert pds.hash_map() is pds.EMPTY_MAP
    assert pds.hash_set() is pds.EMPTY_SET
    assert isinstance(pds.vec(1, 2, 3), pds.Vector)
    assert isinstance(pds.hash_map("answer", 42), pds.Map)
    assert isinstance(pds.hash_set([1, 2, 3]), pds.Set)
