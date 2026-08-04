import os
import uvicorn


def create_app():
    from app.main import app as api_app
    return api_app


app = create_app()


if __name__ == "__main__":
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("SPECGUARD_PORT", "8000")),
        reload=False,
        reload_excludes=["**/unsloth_compiled_cache/**", "**/__pycache__/**", "**/*.pyc"],
    )
