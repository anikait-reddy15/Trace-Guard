from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Integer, ForeignKey, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Document(Base):
    __tablename__ = "documents"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    version_name: Mapped[str] = mapped_column(String(50)) # e.g., "v1.0"
    filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    nodes: Mapped[List["Node"]] = relationship(back_populates="document", cascade="all, delete-orphan")

class Node(Base):
    __tablename__ = "nodes"
    
    # We use a string ID (e.g., "v1_sec4.2") to easily track lineage
    id: Mapped[str] = mapped_column(String(255), primary_key=True) 
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    
    # Self-referential foreign key to build the hierarchy tree
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("nodes.id"))
    level: Mapped[int] = mapped_column(Integer) # 0 = Title, 1 = H1, 2 = H2, etc.
    
    heading: Mapped[Optional[str]] = mapped_column(String(500))
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    
    # CRITICAL for staleness detection. SHA-256 hash of (heading + body_text)
    content_hash: Mapped[str] = mapped_column(String(64)) 
    
    # Tracks if this node was new, modified, or unchanged in the latest version
    status: Mapped[str] = mapped_column(String(20), default="new") 

    document: Mapped["Document"] = relationship(back_populates="nodes")
    parent: Mapped[Optional["Node"]] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[List["Node"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    selections: Mapped[List["SelectionNode"]] = relationship(back_populates="node")

class Selection(Base):
    __tablename__ = "selections"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    nodes: Mapped[List["SelectionNode"]] = relationship(back_populates="selection", cascade="all, delete-orphan")

class SelectionNode(Base):
    """
    Association table. This pins a user's selection to specific versioned nodes.
    If the document updates to v2, this selection still points to the v1 nodes.
    """
    __tablename__ = "selection_nodes"
    
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id"), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), primary_key=True)

    selection: Mapped["Selection"] = relationship(back_populates="nodes")
    node: Mapped["Node"] = relationship(back_populates="selections")