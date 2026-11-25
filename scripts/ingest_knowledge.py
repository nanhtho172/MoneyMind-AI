import argparse
import sys

from backend.app.core.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the embedding model for Knowledge Base uploads.")
    parser.add_argument("--download-model", action="store_true", help="Load the configured model and cache it if needed.")
    args = parser.parse_args()
    if not args.download_model:
        print("Upload documents through the Knowledge Base to index them.")
        return 0
    model_name = Settings().embedding_model
    try:
        if sys.platform == "win32":
            try:
                import pyarrow  
            except ImportError:
                pass
        from sentence_transformers import SentenceTransformer
        SentenceTransformer(model_name, device="cpu")
    except (ImportError, OSError, RuntimeError, ValueError):
        print("Could not load the embedding model. Check requirements-rag.txt, the network and EMBEDDING_MODEL.", file=sys.stderr)
        return 1
    print("Embedding model ready for document uploads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
