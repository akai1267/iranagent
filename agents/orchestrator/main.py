import asyncio
import os

from agents.orchestrator.agent import OrchestratorAgent


async def main() -> None:
    agent = OrchestratorAgent(
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379"),
        groq_key=os.environ.get("GROQ_API_KEY", ""),
    )
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
