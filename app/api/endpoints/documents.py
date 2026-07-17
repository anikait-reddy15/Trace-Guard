import os
import shutil
from typing import List, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.sql_models import Document, Node
from app.schemas.document_schemas import DocumentRead
from app.core.parser import DocumentParser

router = APIRouter(prefix="/documents", tags=["Documents"])

def build_node_tree(nodes: List[Node]) -> List[Dict[str, Any]]:
    """
    Reconstructs the hierarchical tree in memory from a flat list of DB nodes.
    This avoids async lazy-loading issues with SQLAlchemy and Pydantic.
    """
    # Convert DB models to dictionaries
    node_dicts = {
        node.id: {
            "id": node.id,
            "parent_id": node.parent_id,
            "level": node.level,
            "heading": node.heading,
            "body_text": node.body_text,
            "content_hash": node.content_hash,
            "status": node.status,
            "children": []
        }
        for node in nodes
    }
    
    top_level_nodes = []
    
    for node in nodes:
        if node.parent_id and node.parent_id in node_dicts:
            node_dicts[node.parent_id]["children"].append(node_dicts[node.id])
        else:
            top_level_nodes.append(node_dicts[node.id])
            
    return top_level_nodes


@router.post("/ingest", response_model=DocumentRead)
async def ingest_document(
    version_name: str = Form(..., description="e.g., v1.0"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads a PDF manual, parses its heading hierarchy using PyMuPDF,
    computes content hashes, and stores the relational tree in the database.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Prevent duplicate version ingestion
    stmt = select(Document).where(Document.version_name == version_name)
    result = await db.execute(stmt)
    if result.scalars().first():
        raise HTTPException(
            status_code=409, 
            detail=f"Document version '{version_name}' already exists."
        )

    # Persist the file locally for the parser
    os.makedirs("data", exist_ok=True)
    file_path = f"data/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # Trigger the PyMuPDF Parser
        parser = DocumentParser(file_path, version_name)
        parsed_nodes = parser.parse()

        # 1. Create the parent Document record
        new_doc = Document(version_name=version_name, filename=file.filename)
        db.add(new_doc)
        await db.flush() # Flushes to DB to get the new_doc.id without committing

        # 2. Bulk create all Node records
        db_nodes = []
        for n_dict in parsed_nodes:
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
        
        db.add_all(db_nodes)
        await db.commit()

        # 3. Construct the response
        tree = build_node_tree(db_nodes)
        
        return {
            "id": new_doc.id,
            "version_name": new_doc.version_name,
            "filename": new_doc.filename,
            "created_at": new_doc.created_at,
            "nodes": tree
        }

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to process document hierarchy: {str(e)}"
        )


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: int, db: AsyncSession = Depends(get_db)):
    """
    Fetches a document and reconstructs its entire versioned tree structure.
    """
    # Fetch document
    doc_stmt = select(Document).where(Document.id == document_id)
    doc_result = await db.execute(doc_stmt)
    document = doc_result.scalars().first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Fetch all associated nodes
    nodes_stmt = select(Node).where(Node.document_id == document.id).order_by(Node.level)
    nodes_result = await db.execute(nodes_stmt)
    nodes = nodes_result.scalars().all()

    tree = build_node_tree(nodes)

    return {
        "id": document.id,
        "version_name": document.version_name,
        "filename": document.filename,
        "created_at": document.created_at,
        "nodes": tree
    }       