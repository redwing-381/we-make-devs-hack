from falkordb import Edge, Node, Path

from whygraph.graph.client import to_output


def test_paths_become_stable_ids_and_subgraph():
    a = Node(node_id=1, labels="Service", properties={"id": "svc:checkout", "name": "checkout"})
    b = Node(
        node_id=2, labels="Service", properties={"id": "svc:payment", "name": "payment", "embedding": [0.1]}
    )
    e = Edge(1, "CALLS", 2, edge_id=7, properties={"p99_ms": 450})
    out = to_output(["path", "n"], [[Path([a, b], [e]), a]])

    assert out.rows[0]["path"] == {
        "nodes": ["svc:checkout", "svc:payment"],
        "rels": ["svc:checkout|CALLS|svc:payment"],
    }
    assert out.rows[0]["n"]["id"] == "svc:checkout"
    assert {n.id for n in out.subgraph.nodes} == {"svc:checkout", "svc:payment"}
    rel = out.subgraph.rels[0]
    assert (rel.src, rel.type, rel.dst, rel.props["p99_ms"]) == ("svc:checkout", "CALLS", "svc:payment", 450)
    assert all("embedding" not in n.props for n in out.subgraph.nodes)


def test_scalars_pass_through():
    out = to_output(["name", "score"], [["checkout", 0.9]])
    assert out.rows == [{"name": "checkout", "score": 0.9}]
    assert out.subgraph.nodes == []
