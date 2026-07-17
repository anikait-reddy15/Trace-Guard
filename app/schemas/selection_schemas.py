from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
from app.schemas.document_schemas import NodeBase

class SelectionCreate(BaseModel):
    name: str = Field(..., description="A memorable name for this test scope, e.g., 'Cuff Pressure Tests'")
    node_ids: List[str] = Field(..., description="List of specific versioned node IDs to pin.")

class SelectionNodeRead(BaseModel):
    node_id: str
    node: NodeBase # Pulls in the text and hash so we can see what was pinned

    class Config:
        from_attributes = True

class SelectionRead(BaseModel):
    id: int
    name: str
    created_at: datetime
    nodes: List[SelectionNodeRead]

    class Config:
        from_attributes = True