"""AgentCore Memory session manager, scoped to one user (actor) and one Runtime session."""

from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

# Namespaces match the memory strategies defined in infra/lib/stacks/agentcore-stack.ts.
RETRIEVAL_CONFIG = {
    "/facts/{actorId}/": RetrievalConfig(top_k=10, relevance_score=0.4),
    "/preferences/{actorId}/": RetrievalConfig(top_k=5, relevance_score=0.5),
    "/summaries/{actorId}/{sessionId}/": RetrievalConfig(top_k=5, relevance_score=0.4),
    "/episodes/{actorId}/{sessionId}/": RetrievalConfig(top_k=5, relevance_score=0.4),
}


def build_session_manager(
    memory_id: str | None, session_id: str, actor_id: str, region: str | None
) -> AgentCoreMemorySessionManager | None:
    """Return a session manager, or None when no memory is configured."""
    if not memory_id:
        return None
    return AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(
            memory_id=memory_id,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config=RETRIEVAL_CONFIG,
        ),
        region,
    )
