import os

import uvicorn

from rag_agent.app import create_app


if __name__ == "__main__":
    app = create_app()
    uvicorn.run(app, host=os.getenv("RAG_HOST", "127.0.0.1"), port=int(os.getenv("RAG_PORT", "8000")))
