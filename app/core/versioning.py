from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.sql_models import Document, Node
from app.core.parser import DocumentParser
import re

class VersionEngine:   
    def __init__(self, db: AsyncSession):
        self.db = db

    def _normalize_string(self, text: str) -> str:
        """Removes casing, punctuation, and extra spaces for robust matching."""
        if not text: return ""
        return re.sub(r'\W+', '', text).lower()

    async def ingest_new_version(
        self, 
        file_path: str, 
        new_version_name: str, 
        previous_doc_id: int
    ) -> Document:
        """
        Parses a new PDF, diffs it against an older document version,
        and saves the new versioned tree.
        """
        # 1. Fetch previous document's nodes
        stmt = select(Node).where(Node.document_id == previous_doc_id)
        result = await self.db.execute(stmt)
        old_nodes = result.scalars().all()

        # Build a lookup dictionary for old nodes: Key -> (normalized_heading, level)
        old_node_map = {
            (self._normalize_string(n.heading), n.level): n 
            for n in old_nodes
        }

        # 2. Parse the new document
        parser = DocumentParser(file_path, new_version_name)
        new_parsed_nodes = parser.parse()

        # 3. Create the new Document record
        new_doc = Document(version_name=new_version_name, filename=file_path.split("/")[-1])
        self.db.add(new_doc)
        await self.db.flush()

        # 4. Compare and create new nodes
        db_nodes = []
        for n_dict in new_parsed_nodes:
            match_key = (self._normalize_string(n_dict["heading"]), n_dict["level"])
            matched_old_node = old_node_map.get(match_key)

            if matched_old_node:
                # Node exists in both versions. Did the text change?
                if matched_old_node.content_hash == n_dict["content_hash"]:
                    n_dict["status"] = "unchanged"
                else:
                    n_dict["status"] = "modified"
            else:
                # This heading/level combination didn't exist in v1
                n_dict["status"] = "new"

            db_node = Node(
                id=n_dict["id"],
                document_id=new_doc.id,
                parent_id=n_dict["parent_id"],
                level=n_dict["level"],
                heading=n_dict["heading"],
                body_text=n_dict["body_text"],
                content_hash=n_dict["content_hash"],
                status=n_dict["status"]
            )
            db_nodes.append(db_node)

        self.db.add_all(db_nodes)
        await self.db.commit()
        
        return new_doc