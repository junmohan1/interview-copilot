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
        try:
            self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="BAAI/bge-small-zh-v1.5",
                cache_folder=str(MODEL_DIR),
                local_files_only=True
            )
            self.collection = self.client.get_or_create_collection(
                name="interview_notes",
                embedding_function=self.embed_fn
            )
            # 试探性执行一次 count
            self.collection.count()
        except Exception as e:
            print(f"\n[知识库] ⚠️ 检测到向量库损坏: {e}")
            print("[知识库] 正在自动销毁损坏的索引...")
            import shutil
            try:
                del self.client
            except:
                pass
            
            if CHROMA_DIR.exists():
                shutil.rmtree(CHROMA_DIR, ignore_errors=True)
            
            # ★ 优先尝试从备份恢复
            backup_dir = CHROMA_DIR.parent / "chroma_db_backup"
            if backup_dir.exists():
                print("[知识库] 🚑 发现备份库，正在极速恢复...")
                shutil.copytree(backup_dir, CHROMA_DIR)
                self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
                self.collection = self.client.get_or_create_collection(
                    name="interview_notes",
                    embedding_function=self.embed_fn
                )
                print("[知识库] ✅ 已从备份成功恢复！")
            else:
                # ★ 如果没有备份，再走重新解析原文件的慢路
                print("[知识库] ⚠️ 未找到备份，正在从 uploads 目录自动重建...")
                self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
                self.collection = self.client.get_or_create_collection(
                    name="interview_notes",
                    embedding_function=self.embed_fn
                )
                self._auto_rebuild_from_uploads()

    def _auto_rebuild_from_uploads(self):
        """从 data/uploads 目录自动恢复所有资料"""
        from config import UPLOAD_DIR
        if not UPLOAD_DIR.exists():
            return
        
        count = 0
        for file_path in UPLOAD_DIR.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in (".pdf", ".docx", ".txt", ".md", ".xlsx"):
                try:
                    self.load_file(str(file_path))
                    count += 1
                    print(f"  [恢复] 已重新入库: {file_path.name}")
                except Exception as e:
                    print(f"  [恢复失败] {file_path.name}: {e}")
                    
        print(f"[知识库] 🎉 数据恢复完成，共恢复 {count} 个文件。")

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