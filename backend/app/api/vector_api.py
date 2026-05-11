"""
Vector Search API Router
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.vector.gateway import get_vector_gateway

router = APIRouter(prefix="/vector", tags=["vector"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────

class CreateCollectionRequest(BaseModel):
    name: str = Field(..., description="Collection name")
    dimension: int = Field(1536, description="Vector dimension")
    metric: str = Field("cosine", description="Distance metric")
    description: str = Field("", description="Collection description")
    metadata_fields: Optional[List[dict]] = Field(None)


class AddTextsRequest(BaseModel):
    collection: str = Field(..., description="Collection name")
    texts: List[str] = Field(..., min_length=1, max_length=100)
    metadatas: Optional[List[dict]] = Field(None)
    ids: Optional[List[str]] = Field(None)


class SearchRequest(BaseModel):
    collection: str = Field(..., description="Collection name")
    query: str = Field(..., description="Search query")
    limit: int = Field(10, ge=1, le=100)
    where: Optional[dict] = Field(None, description="Metadata filter")


class MemoryStoreRequest(BaseModel):
    content: str = Field(..., description="Content to store in memory")
    memory_type: str = Field("conversation", description="Memory type")
    metadata: Optional[dict] = Field(None)


class MemoryRecallRequest(BaseModel):
    query: str = Field(..., description="Search query")
    limit: int = Field(10, ge=1, le=100)
    memory_type: Optional[str] = Field(None, description="Filter by memory type")


# ─────────────────────────────────────────────────────────────────────────────
# Collection Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/collections")
async def list_collections():
    """List all vector collections"""
    gateway = get_vector_gateway()
    collections = await gateway.list_collections()
    return {"collections": [c.__dict__ for c in collections], "count": len(collections)}


@router.post("/collections")
async def create_collection(req: CreateCollectionRequest):
    """Create a new vector collection"""
    gateway = get_vector_gateway()
    try:
        collection = await gateway.create_collection(
            name=req.name,
            dimension=req.dimension,
            metric=req.metric,
            metadata_fields=req.metadata_fields,
        )
        return {"success": True, "collection": collection.__dict__}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/collections/{name}")
async def delete_collection(name: str):
    """Delete a vector collection"""
    gateway = get_vector_gateway()
    await gateway.delete_collection(name)
    return {"success": True, "message": f"Collection '{name}' deleted"}


# ─────────────────────────────────────────────────────────────────────────────
# Vector Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/add")
async def add_texts(req: AddTextsRequest):
    """Add texts to a collection (auto-embeds)"""
    gateway = get_vector_gateway()
    try:
        ids = await gateway.add_texts(
            collection=req.collection,
            texts=req.texts,
            metadatas=req.metadatas,
            ids=req.ids,
        )
        return {"success": True, "ids": ids, "count": len(ids)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def search_vectors(req: SearchRequest):
    """Search for similar vectors"""
    gateway = get_vector_gateway()
    try:
        results = await gateway.search(
            collection=req.collection,
            query=req.query,
            limit=req.limit,
            where=req.where,
        )
        return {
            "success": True,
            "query": req.query,
            "results": [
                {
                    "id": r.id,
                    "text": r.text[:500],
                    "score": round(r.score, 4),
                    "metadata": r.metadata,
                }
                for r in results
            ],
            "count": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{collection}/vectors")
async def delete_vectors(collection: str, ids: Optional[List[str]] = None):
    """Delete vectors from a collection"""
    gateway = get_vector_gateway()
    if ids:
        deleted = await gateway.delete_by_ids(collection, ids)
    else:
        raise HTTPException(status_code=400, detail="ids parameter required")
    return {"success": True, "deleted": deleted}


# ─────────────────────────────────────────────────────────────────────────────
# Memory Integration Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/memory/store")
async def store_memory(req: MemoryStoreRequest):
    """Store content in vector memory"""
    gateway = get_vector_gateway()
    try:
        vector_id = await gateway.store_memory(
            content=req.content,
            memory_type=req.memory_type,
            metadata=req.metadata,
        )
        return {"success": True, "id": vector_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/recall")
async def recall_memory(req: MemoryRecallRequest):
    """Recall relevant memories"""
    gateway = get_vector_gateway()
    try:
        results = await gateway.recall_memory(
            query=req.query,
            limit=req.limit,
            memory_type=req.memory_type,
        )
        return {
            "success": True,
            "query": req.query,
            "results": [
                {
                    "id": r.id,
                    "text": r.text[:500],
                    "score": round(r.score, 4),
                    "metadata": r.metadata,
                }
                for r in results
            ],
            "count": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Bulk Operations
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
async def vector_health():
    """Check vector service health"""
    gateway = get_vector_gateway()
    try:
        collections = await gateway.list_collections()
        return {
            "success": True,
            "engine": "pgvector",
            "collections_count": len(collections),
            "collections": [c.name for c in collections],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
