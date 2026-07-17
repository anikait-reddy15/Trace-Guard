from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.sql_models import Node, Selection, SelectionNode
from app.schemas.selection_schemas import SelectionCreate, SelectionRead

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