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
from app.graph.nodes.hitl_decision_node import HitlDecisionNode
from app.graph.nodes.letter_generation_node import LetterGenerationNode
from app.graph.state import ClaimGraphState
from app.llm.base import LLMClient
from app.services.rule_engine import RuleEngine


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

    @staticmethod
    def _build_graph(llm_client: LLMClient, rule_engine: RuleEngine) -> StateGraph:
        graph = StateGraph(ClaimGraphState)
        graph.add_node("document_ingestion", DocumentIngestionNode())
        graph.add_node("document_classification", DocumentClassificationNode(llm_client))
        graph.add_node("entity_extraction", EntityExtractionNode(llm_client))
        graph.add_node("extraction_quality_validation", ExtractionQualityValidationNode(rule_engine))
        graph.add_node("business_rule_validation", BusinessValidationNode(rule_engine))
        graph.add_node("hitl_decision", HitlDecisionNode(rule_engine, llm_client))
        graph.add_node("letter_or_summary_generation", LetterGenerationNode(llm_client))
        graph.add_node("audit_logging", AuditLoggingNode(rule_engine))

        graph.add_edge(START, "document_ingestion")
        graph.add_conditional_edges(
            "document_ingestion",
            ClaimWorkflowGraph._route_after_ingestion,
            {
                "continue": "document_classification",
                "end": END,
            },
        )
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
        graph.add_node("hitl_decision", HitlDecisionNode(rule_engine, llm_client))
        graph.add_node("letter_or_summary_generation", LetterGenerationNode(llm_client))
        graph.add_node("audit_logging", AuditLoggingNode(rule_engine))
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
