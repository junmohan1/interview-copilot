"""ChromaDB 知识库，支持上传文件、检索片段"""
import hashlib
from pathlib import Path
from typing import List

import chromadb
from chromadb.utils import embedding_functions

from config import CHROMA_DIR, MODEL_DIR
from .file_parser import parse_file


class KnowledgeBase:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        # ★ 强制离线加载本地已下载的模型，绝不去联网请求
        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="BAAI/bge-small-zh-v1.5",
            cache_folder=str(MODEL_DIR),
            local_files_only=True  # ★ 加上这一行
        )
        self.collection = self.client.get_or_create_collection(
            name="interview_notes",
            embedding_function=self.embed_fn
        )

    def add_document(self, text: str, metadata: dict = None, doc_id: str = None):
        if not text.strip():
            return
        doc_id = doc_id or hashlib.md5(text.encode()).hexdigest()
        self.collection.add(
            documents=[text],
            metadatas=[metadata or {}],
            ids=[doc_id]
        )

    def search(self, query: str, top_k: int = 3) -> List[str]:
        if self.collection.count() == 0:
            return []
        results = self.collection.query(
            query_texts=[query],
            n_results=min(top_k, self.collection.count())
        )
        return results["documents"][0] if results["documents"] else []

    def load_file(self, file_path: str, chunk_size: int = 500):
        text = parse_file(file_path)
        name = Path(file_path).name
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        for i, chunk in enumerate(chunks):
            self.add_document(
                chunk,
                metadata={"source": name, "chunk": i},
                doc_id=f"{name}_{i}"
            )
        return len(chunks)

    def list_sources(self) -> List[str]:
        if self.collection.count() == 0:
            return []
        data = self.collection.get(include=["metadatas"])
        return sorted({m.get("source", "?") for m in data["metadatas"]})

    def clear(self):
        self.client.delete_collection("interview_notes")
        self.collection = self.client.get_or_create_collection(
            name="interview_notes",
            embedding_function=self.embed_fn
        )

    def delete_source(self, source_name: str) -> int:
        """删除某个文件对应的所有 chunks，返回删除数量"""
        if self.collection.count() == 0:
            return 0
        data = self.collection.get(
            where={"source": source_name},
            include=["metadatas"]
        )
        ids = data.get("ids", [])
        if not ids:
            return 0
        self.collection.delete(ids=ids)
        return len(ids)        