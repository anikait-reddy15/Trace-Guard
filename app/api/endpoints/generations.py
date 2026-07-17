from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.database import get_db, get_mongo_collection
from app.models.sql_models import Selection, SelectionNode
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
    """
    Generates QA test cases for a specific selection.
    Implements caching to prevent redundant LLM calls unless force_regenerate is True.
    """
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
    source_snapshots = {} # Maps node_id -> content_hash for staleness tracking
    
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
        # We explicitly catch validation/retry failures and return a 422
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected AI Error: {str(e)}")

    # 5. Build the immutable MongoDB Document
    mongo_doc = {
        "selection_id": request.selection_id,
        "generated_at": datetime.utcnow().isoformat(),
        # Store the exact state of the text when the LLM read it
        "source_node_hashes": source_snapshots, 
        "test_cases": [tc.model_dump() for tc in generation_result.test_cases]
    }

    # 6. Save or Update in MongoDB
    await mongo_collection.update_one(
        {"selection_id": request.selection_id},
        {"$set": mongo_doc},
        upsert=True
    )

    # Return without the MongoDB ObjectId for clean JSON
    mongo_doc.pop("_id", None) 
    mongo_doc["cached_response"] = False
    return mongo_doc


@router.get("/{selection_id}", response_model=dict)
async def get_generation(
    selection_id: int,
    mongo_collection = Depends(get_mongo_collection)
):
    """Fetches previously generated test cases by selection ID."""
    existing_gen = await mongo_collection.find_one({"selection_id": selection_id})
    if not existing_gen:
        raise HTTPException(status_code=404, detail="No generations found for this selection.")
    
    existing_gen["_id"] = str(existing_gen["_id"])
    return existing_gen 