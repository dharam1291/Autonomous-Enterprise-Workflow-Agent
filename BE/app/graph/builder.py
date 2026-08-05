from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.domain.models import WorkflowStatus
from app.graph.nodes.audit_logging_node import AuditLoggingNode
from app.graph.nodes.business_validation_node import BusinessValidationNode
from app.graph.nodes.document_classification_node import DocumentClassificationNode
from app.graph.nodes.document_ingestion_node import DocumentIngestionNode
from app.graph.nodes.entity_extraction_node import EntityExtractionNode
from app.graph.nodes.extraction_quality_validation_node import ExtractionQualityValidationNode
from app.graph.nodes.guardrail_inputs_node import GuardrailInputsNode
from app.graph.nodes.hitl_decision_node import HitlDecisionNode
from app.graph.nodes.letter_generation_node import LetterGenerationNode
from app.graph.state import ClaimGraphState
from app.llm.clients.base_client import LLMClient
from app.observability import instrument_node
from app.services.rule_engine import RuleEngine


def _add_node(graph: StateGraph, name: str, node) -> None:
    """Register a node wrapped with observability (span + node metrics)."""
    graph.add_node(name, instrument_node(name, node))


# Callout captions attached to a node in the Mermaid diagram. Each renders as a
# separate dashed note pointing at the node (the node itself keeps just its id),
# so the diagram explains what a step does. Extend as more steps deserve one.
NODE_CAPTIONS: dict[str, str] = {
    "guardrail_inputs": "PII Validation",
}

_CAPTION_CLASSDEF = (
    "\tclassDef caption fill:#fff8e6,stroke:#d9a441,stroke-dasharray:4 3,color:#7a5b00"
)


def _annotate_mermaid(mermaid: str) -> str:
    """Attach caption notes to nodes in a LangGraph-generated diagram.

    draw_mermaid() renders each node as ``id(id)``. For each captioned node we
    add a separate note node and a dashed arrow pointing at it, e.g.::

        guardrail_inputs__caption[PII Validation]:::caption
        guardrail_inputs__caption -.-> guardrail_inputs
    """
    lines = mermaid.splitlines()
    annotated: list[str] = []
    added = False
    for line in lines:
        annotated.append(line)
        node_id = line.strip().removesuffix(")").rsplit("(", 1)[0] if line.strip().endswith(")") else ""
        caption = NODE_CAPTIONS.get(node_id)
        if caption and line.strip() == f"{node_id}({node_id})":
            caption_id = f"{node_id}__caption"
            annotated.append(f'\t{caption_id}["{caption}"]:::caption')
            annotated.append(f"\t{caption_id} -.-> {node_id}")
            added = True
    if added:
        annotated.append(_CAPTION_CLASSDEF)
    return "\n".join(annotated)


class ClaimWorkflowGraph:
    def __init__(
        self,
        llm_client: LLMClient,
        rule_engine: RuleEngine,
        checkpointer: MemorySaver | None = None,
    ) -> None:
        saver = checkpointer or MemorySaver()
        self._graph = self._build_graph(llm_client, rule_engine).compile(checkpointer=saver)
        self._resume_graph = self._build_resume_graph(llm_client, rule_engine).compile(checkpointer=saver)

    def run(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow_id = state["workflow"].workflow_id
        return self._graph.invoke(
            state,
            config={"configurable": {"thread_id": workflow_id}},
        )

    def resume_after_review(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow_id = state["workflow"].workflow_id
        return self._resume_graph.invoke(
            state,
            config={"configurable": {"thread_id": workflow_id}},
        )

    def draw_mermaid(self) -> str:
        """Mermaid definition of the full start-to-end claim graph."""
        return _annotate_mermaid(self._graph.get_graph().draw_mermaid())

    def draw_resume_mermaid(self) -> str:
        """Mermaid definition of the post-human-review resume graph."""
        return _annotate_mermaid(self._resume_graph.get_graph().draw_mermaid())

    def node_names(self) -> list[str]:
        return self._executable_nodes(self._graph)

    def resume_node_names(self) -> list[str]:
        return self._executable_nodes(self._resume_graph)

    @staticmethod
    def _executable_nodes(compiled) -> list[str]:
        return [nid for nid in compiled.get_graph().nodes if not nid.startswith("__")]

    @classmethod
    def for_visualization(cls) -> "ClaimWorkflowGraph":
        """Build a graph purely to inspect its topology.

        Uses the dependency-free deterministic client so no provider API keys
        are required just to render the diagram.
        """
        from app.llm.clients.deterministic_client import DeterministicLLMClient

        return cls(llm_client=DeterministicLLMClient(), rule_engine=RuleEngine())

    @staticmethod
    def _build_graph(llm_client: LLMClient, rule_engine: RuleEngine) -> StateGraph:
        graph = StateGraph(ClaimGraphState)
        _add_node(graph, "document_ingestion", DocumentIngestionNode())
        _add_node(graph, "guardrail_inputs", GuardrailInputsNode())
        _add_node(graph, "document_classification", DocumentClassificationNode(llm_client))
        _add_node(graph, "entity_extraction", EntityExtractionNode(llm_client))
        _add_node(graph, "extraction_quality_validation", ExtractionQualityValidationNode(rule_engine))
        _add_node(graph, "business_rule_validation", BusinessValidationNode(rule_engine))
        _add_node(graph, "hitl_decision", HitlDecisionNode(rule_engine, llm_client))
        _add_node(graph, "letter_or_summary_generation", LetterGenerationNode(llm_client))
        _add_node(graph, "audit_logging", AuditLoggingNode(rule_engine))

        graph.add_edge(START, "document_ingestion")
        graph.add_conditional_edges(
            "document_ingestion",
            ClaimWorkflowGraph._route_after_ingestion,
            {
                "continue": "guardrail_inputs",
                "end": END,
            },
        )
        graph.add_edge("guardrail_inputs", "document_classification")
        graph.add_conditional_edges(
            "document_classification",
            ClaimWorkflowGraph._route_after_classification,
            {
                "continue": "entity_extraction",
                "end": END,
            },
        )
        graph.add_edge("entity_extraction", "extraction_quality_validation")
        graph.add_edge("extraction_quality_validation", "business_rule_validation")
        graph.add_edge("business_rule_validation", "hitl_decision")
        graph.add_conditional_edges(
            "hitl_decision",
            ClaimWorkflowGraph._route_after_hitl,
            {
                "pause": END,
                "continue": "letter_or_summary_generation",
            },
        )
        graph.add_edge("letter_or_summary_generation", "audit_logging")
        graph.add_edge("audit_logging", END)
        return graph

    @staticmethod
    def _build_resume_graph(llm_client: LLMClient, rule_engine: RuleEngine) -> StateGraph:
        graph = StateGraph(ClaimGraphState)
        _add_node(graph, "hitl_decision", HitlDecisionNode(rule_engine, llm_client))
        _add_node(graph, "letter_or_summary_generation", LetterGenerationNode(llm_client))
        _add_node(graph, "audit_logging", AuditLoggingNode(rule_engine))
        graph.add_edge(START, "hitl_decision")
        graph.add_edge("hitl_decision", "letter_or_summary_generation")
        graph.add_edge("letter_or_summary_generation", "audit_logging")
        graph.add_edge("audit_logging", END)
        return graph

    @staticmethod
    def _route_after_ingestion(state: ClaimGraphState) -> str:
        return "end" if state["workflow"].status == WorkflowStatus.UNSUPPORTED_PROVIDER else "continue"

    @staticmethod
    def _route_after_classification(state: ClaimGraphState) -> str:
        return "end" if state["workflow"].status == WorkflowStatus.INVALID_DOCUMENT else "continue"

    @staticmethod
    def _route_after_hitl(state: ClaimGraphState) -> str:
        return "pause" if state["workflow"].status == WorkflowStatus.WAITING_FOR_HUMAN_REVIEW else "continue"
