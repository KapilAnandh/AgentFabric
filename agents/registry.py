from agents.research.research_agent import ResearchAgent
from agents.coding.coding_agent import CodingAgent
from agents.qa.qa_agent import QAAgent
from agents.report.report_agent import ReportAgent
from agents.vision.vision_agent import VisionAgent
from agents.base_agent import BaseAgent


class AgentRegistry:
    """Central registry for all agent types in the ARP system."""

    AGENT_MAP = {
        "research": ResearchAgent,
        "coding": CodingAgent,
        "qa": QAAgent,
        "report": ReportAgent,
        "vision": VisionAgent,
        "general": ResearchAgent
    }

    @classmethod
    def get_agent(cls, task_type: str, agent_id: str, model_name: str, token_manager) -> BaseAgent:
        """
        Get an instantiated agent for the specified task type.

        Args:
            task_type: Type of task (research, coding, qa, report, vision, general)
            agent_id: Unique identifier for the agent instance
            model_name: Name of the LLM model to use
            token_manager: Token manager instance for resource tracking

        Returns:
            Instantiated agent of the appropriate type
        """
        agent_class = cls.AGENT_MAP.get(task_type, ResearchAgent)
        return agent_class(agent_id, model_name, token_manager)

    @classmethod
    def get_available_types(cls) -> list[str]:
        """Get list of all available agent types."""
        return list(cls.AGENT_MAP.keys())
