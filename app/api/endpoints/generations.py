from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.database import get_db, get_mongo_collection
from app.models.sql_models import Selection, SelectionNode, Document, Node
from app.core.llm_engine import QAEngine, LLMGenerationError
from pydantic import BaseModel

router = APIRouter(prefix="/generations", tags=["Generations"])

class GenerationRequest(BaseModel):
    selection_id: int
    force_regenerate: bool = False

@router.post("/", response_model=dict)
async def generate_test_cases(
    request: GenerationRequest,
    db: AsyncSession = Depends(get_db),
    mongo_collection = Depends(get_mongo_collection)
):
    # 1. Enforce Idempotency Policy (Cache Check)
    if not request.force_regenerate:
        existing_gen = await mongo_collection.find_one({"selection_id": request.selection_id})
        if existing_gen:
            existing_gen["_id"] = str(existing_gen["_id"])
            existing_gen["cached_response"] = True
            return existing_gen

    # 2. Fetch the Pinned Selection & Text from SQLite
    stmt = (
        select(Selection)
        .options(selectinload(Selection.nodes).selectinload(SelectionNode.node))
        .where(Selection.id == request.selection_id)
    )
    result = await db.execute(stmt)
    selection = result.scalars().first()

    if not selection:
        raise HTTPException(status_code=404, detail="Selection not found.")
    
    if not selection.nodes:
        raise HTTPException(status_code=400, detail="Selection has no nodes attached.")

    # 3. Prepare data for the LLM
    nodes_for_llm = []
    source_snapshots = {} 
    
    for sn in selection.nodes:
        nodes_for_llm.append({
            "node_id": sn.node.id,
            "node": {
                "heading": sn.node.heading,
                "body_text": sn.node.body_text
            }
        })
        source_snapshots[sn.node.id] = sn.node.content_hash

    # 4. Trigger the LLM Engine
    qa_engine = QAEngine()
    try:
        generation_result = await qa_engine.generate_test_cases(nodes_for_llm)
    except LLMGenerationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected AI Error: {str(e)}")

    # 5. Build the immutable MongoDB Document
    mongo_doc = {
        "selection_id": request.selection_id,
        "generated_at": datetime.utcnow().isoformat(),
        "source_node_hashes": source_snapshots, 
        "test_cases": [tc.model_dump() for tc in generation_result.test_cases]
    }

    # 6. Save or Update in MongoDB
    await mongo_collection.update_one(
        {"selection_id": request.selection_id},
        {"$set": mongo_doc},
        upsert=True
    )

    mongo_doc.pop("_id", None) 
    mongo_doc["cached_response"] = False
    return mongo_doc


@router.get("/{selection_id}", response_model=dict)
async def get_generation(
    selection_id: int,
    mongo_collection = Depends(get_mongo_collection)
):
    existing_gen = await mongo_collection.find_one({"selection_id": selection_id})
    if not existing_gen:
        raise HTTPException(status_code=404, detail="No generations found for this selection.")
    
    existing_gen["_id"] = str(existing_gen["_id"])
    return existing_gen


@router.get("/{selection_id}/staleness", response_model=dict)
async def check_staleness(
    selection_id: int,
    db: AsyncSession = Depends(get_db),
    mongo_collection = Depends(get_mongo_collection)
):
    # 1. Fetch the frozen generation record from MongoDB
    gen_doc = await mongo_collection.find_one({"selection_id": selection_id})
    if not gen_doc:
        raise HTTPException(status_code=404, detail="No generations found for this selection.")
        
    source_hashes = gen_doc.get("source_node_hashes", {})
    if not source_hashes:
        return {"overall_status": "UNKNOWN", "detail": "Legacy generation without hash tracking."}

    # 2. Identify the absolute latest document in the system
    latest_doc_stmt = select(Document).order_by(Document.created_at.desc()).limit(1)
    latest_doc = (await db.execute(latest_doc_stmt)).scalars().first()
    
    if not latest_doc:
        raise HTTPException(status_code=404, detail="No documents exist in the system.")

    # 3. Fetch the original nodes from SQLite to know their headings and levels
    original_node_ids = list(source_hashes.keys())
    orig_nodes_stmt = select(Node).where(Node.id.in_(original_node_ids))
    orig_nodes = {n.id: n for n in (await db.execute(orig_nodes_stmt)).scalars().all()}

    audit_results = []
    is_selection_stale = False

    # 4. Cross-reference the frozen hashes against the live latest document
    for orig_id, saved_hash in source_hashes.items():
        orig_node = orig_nodes.get(orig_id)
        if not orig_node:
            continue
            
        counterpart_stmt = select(Node).where(
            Node.document_id == latest_doc.id,
            Node.heading == orig_node.heading,
            Node.level == orig_node.level
        )
        counterpart_node = (await db.execute(counterpart_stmt)).scalars().first()
        
        node_audit = {
            "original_node_id": orig_id,
            "heading": orig_node.heading,
            "saved_hash": saved_hash,
            "latest_document_version": latest_doc.version_name,
        }
        
        if not counterpart_node:
            node_audit["status"] = "DELETED"
            node_audit["is_stale"] = True
            node_audit["reason"] = "The section heading no longer exists in the latest manual."
        elif counterpart_node.content_hash != saved_hash:
            node_audit["status"] = "MODIFIED"
            node_audit["is_stale"] = True
            node_audit["latest_hash"] = counterpart_node.content_hash
            node_audit["latest_node_id"] = counterpart_node.id
            node_audit["reason"] = "The body text of this section has been modified."
        else:
            node_audit["status"] = "UNCHANGED"
            node_audit["is_stale"] = False
            node_audit["latest_hash"] = counterpart_node.content_hash
            node_audit["latest_node_id"] = counterpart_node.id
            node_audit["reason"] = "Text is identical to generation time."
            
        if node_audit["is_stale"]:
            is_selection_stale = True
            
        audit_results.append(node_audit)
        
    return {
        "selection_id": selection_id,
        "overall_status": "STALE" if is_selection_stale else "FRESH",
        "audited_against_version": latest_doc.version_name,
        "node_audits": audit_results
    }