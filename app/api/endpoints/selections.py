from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.sql_models import Selection, SelectionNode, Document, Node
from app.schemas.selection_schemas import SelectionCreate, SelectionRead
from app.database import get_db, get_mongo_collection   

router = APIRouter(prefix="/selections", tags=["Selections"])

@router.post("/", response_model=SelectionRead)
async def create_selection(
    selection_in: SelectionCreate, 
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a named selection of nodes. Because node_ids contain the version prefix
    (e.g., 'v1_node_X'), this permanently pins the selection to that specific version's text.
    """
    if not selection_in.node_ids:
        raise HTTPException(status_code=400, detail="Must provide at least one node_id.")

    # 1. Validate that all requested nodes actually exist in the database
    stmt = select(Node).where(Node.id.in_(selection_in.node_ids))
    result = await db.execute(stmt)
    existing_nodes = result.scalars().all()
    
    if len(existing_nodes) != len(selection_in.node_ids):
        found_ids = {n.id for n in existing_nodes}
        missing = set(selection_in.node_ids) - found_ids
        raise HTTPException(status_code=404, detail=f"Nodes not found in DB: {missing}")

    # 2. Create the parent Selection record
    new_selection = Selection(name=selection_in.name)
    db.add(new_selection)
    await db.flush() # Flush to get the new selection ID

    # 3. Create the many-to-many linkages
    sel_nodes = [
        SelectionNode(selection_id=new_selection.id, node_id=nid) 
        for nid in selection_in.node_ids
    ]
    db.add_all(sel_nodes)
    await db.commit()
    
    # 4. Fetch the created selection with all its child relationships loaded
    fetch_stmt = (
        select(Selection)
        .options(selectinload(Selection.nodes).selectinload(SelectionNode.node))
        .where(Selection.id == new_selection.id)
    )
    final_res = await db.execute(fetch_stmt)
    
    return final_res.scalars().first()

@router.get("/{selection_id}", response_model=SelectionRead)
async def get_selection(
    selection_id: int, 
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves a pinned selection and the exact node text it was pinned to.
    """
    stmt = (
        select(Selection)
        .options(selectinload(Selection.nodes).selectinload(SelectionNode.node))
        .where(Selection.id == selection_id)
    )
    result = await db.execute(stmt)
    selection = result.scalars().first()
    
    if not selection:
        raise HTTPException(status_code=404, detail="Selection not found.")
        
    return selection

@router.get("/{selection_id}/staleness", response_model=dict)
async def check_staleness(
    selection_id: int,
    db: AsyncSession = Depends(get_db),
    mongo_collection = Depends(get_mongo_collection)
):
    """
    Audits a previously generated test suite against the absolute latest
    version of the document to determine if the test cases are STALE (outdated).
    """
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
            
        # Look for this exact heading/level in the NEWEST document
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