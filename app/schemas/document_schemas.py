from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class NodeBase(BaseModel):
    level: int
    heading: Optional[str] = None
    body_text: Optional[str] = None
    content_hash: str
    status: str

class NodeRead(NodeBase):
    id: str
    parent_id: Optional[str] = None
    # Recursive reference to rebuild the tree in JSON responses
    children: List["NodeRead"] = [] 

    class Config:
        from_attributes = True

class DocumentRead(BaseModel):
    id: int
    version_name: str
    filename: str
    created_at: datetime
    # Returns only top-level nodes (level 0 or 1), which recursively fetch their children
    nodes: List[NodeRead] = []

    class Config:
        from_attributes = True

class SelectionCreate(BaseModel):
    name: str
    node_ids: List[str] = Field(..., description="List of specific versioned node IDs to pin.")