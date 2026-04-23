"""Unit tests for workflow_compiler — compile WorkflowDoc → DAG."""
import pytest
from app.services.workflow_compiler import compile_workflow, CompiledWorkflow, SUPPORTED_NODE_TYPES


def _make_doc(nodes, edges=None, name="test"):
    return {"name": name, "nodes": nodes, "edges": edges or []}


class TestCompileBasic:
    def test_single_llm_node(self):
        doc = _make_doc([
            {"id": "n1", "type": "llm", "data": {"label": "Plan", "prompt": "hello"}}
        ])
        cw = compile_workflow(doc)
        assert isinstance(cw, CompiledWorkflow)
        assert cw.name == "test"
        assert len(cw.nodes) == 1
        assert cw.nodes[0].node_type == "llm"
        assert cw.nodes[0].config["prompt"] == "hello"

    def test_empty_nodes_raises(self):
        with pytest.raises(ValueError, match="no nodes"):
            compile_workflow(_make_doc([]))

    def test_edge_dependencies(self):
        doc = _make_doc(
            [
                {"id": "a", "type": "llm", "data": {"label": "A"}},
                {"id": "b", "type": "llm", "data": {"label": "B"}},
                {"id": "c", "type": "llm", "data": {"label": "C"}},
            ],
            [
                {"id": "e1", "source": "a", "target": "b"},
                {"id": "e2", "source": "a", "target": "c"},
                {"id": "e3", "source": "b", "target": "c"},
            ],
        )
        cw = compile_workflow(doc)
        node_map = {n.node_id: n for n in cw.nodes}
        assert node_map["a"].depends_on == []
        assert node_map["b"].depends_on == ["a"]
        assert set(node_map["c"].depends_on) == {"a", "b"}

    def test_duplicate_ids_deduped(self):
        doc = _make_doc([
            {"id": "x", "type": "llm", "data": {"label": "X"}},
            {"id": "x", "type": "llm", "data": {"label": "X2"}},
        ])
        cw = compile_workflow(doc)
        assert len(cw.nodes) == 1


class TestNodeTypes:
    @pytest.mark.parametrize("ntype", list(SUPPORTED_NODE_TYPES))
    def test_supported_type(self, ntype):
        doc = _make_doc([{"id": "n", "type": ntype, "data": {"label": "test"}}])
        cw = compile_workflow(doc)
        assert cw.nodes[0].node_type == ntype

    def test_unsupported_type_falls_back_to_llm(self):
        doc = _make_doc([{"id": "n", "type": "unknown_magic", "data": {"label": "X"}}])
        cw = compile_workflow(doc)
        assert cw.nodes[0].node_type == "llm"


class TestConfigExtraction:
    def test_http_config(self):
        doc = _make_doc([{
            "id": "h", "type": "http",
            "data": {"label": "API Call", "url": "https://example.com", "method": "POST"},
        }])
        cw = compile_workflow(doc)
        assert cw.nodes[0].config["url"] == "https://example.com"
        assert cw.nodes[0].config["method"] == "POST"

    def test_tool_config(self):
        doc = _make_doc([{
            "id": "t", "type": "tool",
            "data": {"label": "Run", "toolName": "code_exec", "arguments": {"code": "print(1)"}},
        }])
        cw = compile_workflow(doc)
        assert cw.nodes[0].config["tool_name"] == "code_exec"

    def test_to_dict_roundtrip(self):
        doc = _make_doc([
            {"id": "a", "type": "llm", "data": {"label": "A", "prompt": "hi"}},
            {"id": "b", "type": "http", "data": {"label": "B", "url": "http://x"}},
        ], [{"id": "e", "source": "a", "target": "b"}])
        cw = compile_workflow(doc)
        d = cw.to_dict()
        assert d["name"] == "test"
        assert len(d["nodes"]) == 2
        assert d["nodes"][1]["depends_on"] == ["a"]
