import logging
from datetime import UTC, datetime
from typing import List, Optional, Set
from uuid import UUID

from app.database import get_db
from app.models import (
    AccessControl,
    App,
    Category,
    FeedbackStatus,
    Memory,
    MemoryAccessLog,
    MemoryFeedback,
    MemoryHistory,
    MemoryState,
    MemoryStatusHistory,
    User,
)
from app.schemas import (
    FeedbackByStatusRequest,
    FeedbackListResponse,
    FeedbackRecordResponse,
    FeedbackSubmitRequest,
    MemoryHistoryResponse,
    MemoryResponse,
)
from app.utils.memory import get_memory_client
from app.utils.permissions import check_memory_access_permissions
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlalchemy import paginate as sqlalchemy_paginate
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


def _batch_feedback_statuses(db: Session, memory_ids: list) -> dict:
    if not memory_ids:
        return {}
    latest_sub = db.query(
        MemoryFeedback.memory_id,
        func.max(MemoryFeedback.created_at).label("max_created_at"),
    ).filter(
        MemoryFeedback.memory_id.in_(memory_ids)
    ).group_by(MemoryFeedback.memory_id).subquery()

    rows = db.query(
        MemoryFeedback.memory_id,
        MemoryFeedback.status,
    ).join(
        latest_sub,
        (MemoryFeedback.memory_id == latest_sub.c.memory_id)
        & (MemoryFeedback.created_at == latest_sub.c.max_created_at),
    ).all()

    result = {str(row.memory_id): row.status.value for row in rows}
    for mid in memory_ids:
        key = str(mid)
        if key not in result:
            result[key] = "unreviewed"
    return result


def get_memory_or_404(db: Session, memory_id: UUID) -> Memory:
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


def update_memory_state(db: Session, memory_id: UUID, new_state: MemoryState, user_id: UUID):
    memory = get_memory_or_404(db, memory_id)
    old_state = memory.state

    # Update memory state
    memory.state = new_state
    if new_state == MemoryState.archived:
        memory.archived_at = datetime.now(UTC)
    elif new_state == MemoryState.deleted:
        memory.deleted_at = datetime.now(UTC)
        # Record a DELETE content history event for traceability
        db.add(MemoryHistory(
            memory_id=memory_id,
            event="DELETE",
            old_memory=memory.content,
            new_memory=None,
        ))

    # Record state change
    history = MemoryStatusHistory(
        memory_id=memory_id,
        changed_by=user_id,
        old_state=old_state,
        new_state=new_state
    )
    db.add(history)
    db.commit()
    return memory


def get_accessible_memory_ids(db: Session, app_id: UUID) -> Set[UUID]:
    """
    Get the set of memory IDs that the app has access to based on app-level ACL rules.
    Returns all memory IDs if no specific restrictions are found.
    """
    # Get app-level access controls
    app_access = db.query(AccessControl).filter(
        AccessControl.subject_type == "app",
        AccessControl.subject_id == app_id,
        AccessControl.object_type == "memory"
    ).all()

    # If no app-level rules exist, return None to indicate all memories are accessible
    if not app_access:
        return None

    # Initialize sets for allowed and denied memory IDs
    allowed_memory_ids = set()
    denied_memory_ids = set()

    # Process app-level rules
    for rule in app_access:
        if rule.effect == "allow":
            if rule.object_id:  # Specific memory access
                allowed_memory_ids.add(rule.object_id)
            else:  # All memories access
                return None  # All memories allowed
        elif rule.effect == "deny":
            if rule.object_id:  # Specific memory denied
                denied_memory_ids.add(rule.object_id)
            else:  # All memories denied
                return set()  # No memories accessible

    # Remove denied memories from allowed set
    if allowed_memory_ids:
        allowed_memory_ids -= denied_memory_ids

    return allowed_memory_ids


# List all memories with filtering
@router.get("/", response_model=Page[MemoryResponse])
async def list_memories(
    user_id: str,
    app_id: Optional[UUID] = None,
    from_date: Optional[int] = Query(
        None,
        description="Filter memories created after this date (timestamp)",
        examples=[1718505600]
    ),
    to_date: Optional[int] = Query(
        None,
        description="Filter memories created before this date (timestamp)",
        examples=[1718505600]
    ),
    categories: Optional[str] = None,
    params: Params = Depends(),
    search_query: Optional[str] = None,
    sort_column: Optional[str] = Query(None, description="Column to sort by (memory, categories, app_name, created_at)"),
    sort_direction: Optional[str] = Query(None, description="Sort direction (asc or desc)"),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Build base query
    query = db.query(Memory).filter(
        Memory.user_id == user.id,
        Memory.state != MemoryState.deleted,
        Memory.state != MemoryState.archived,
        Memory.content.ilike(f"%{search_query}%") if search_query else True
    )

    # Apply filters
    if app_id:
        query = query.filter(Memory.app_id == app_id)

    if from_date:
        from_datetime = datetime.fromtimestamp(from_date, tz=UTC)
        query = query.filter(Memory.created_at >= from_datetime)

    if to_date:
        to_datetime = datetime.fromtimestamp(to_date, tz=UTC)
        query = query.filter(Memory.created_at <= to_datetime)

    # Add joins for app and categories after filtering
    query = query.outerjoin(App, Memory.app_id == App.id)
    query = query.outerjoin(Memory.categories)

    # Apply category filter if provided
    if categories:
        category_list = [c.strip() for c in categories.split(",")]
        query = query.filter(Category.name.in_(category_list))

    # Apply sorting if specified
    if sort_column:
        sort_field = getattr(Memory, sort_column, None)
        if sort_field:
            query = query.order_by(sort_field.desc()) if sort_direction == "desc" else query.order_by(sort_field.asc())

    # Add eager loading for app and categories
    query = query.options(
        joinedload(Memory.app),
        joinedload(Memory.categories)
    ).distinct(Memory.id)

    all_items = query.all()
    fb_map = _batch_feedback_statuses(db, [m.id for m in all_items])

    return sqlalchemy_paginate(
        query,
        params,
        transformer=lambda items: [
            MemoryResponse(
                id=memory.id,
                content=memory.content,
                created_at=memory.created_at,
                state=memory.state.value,
                app_id=memory.app_id,
                app_name=memory.app.name if memory.app else None,
                categories=[category.name for category in memory.categories],
                metadata_=memory.metadata_,
                feedback_status=fb_map.get(str(memory.id)),
            )
            for memory in items
            if check_memory_access_permissions(db, memory, app_id)
        ]
    )


# Get all categories
@router.get("/categories")
async def get_categories(
    user_id: str,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get unique categories associated with the user's memories
    # Get all memories
    memories = db.query(Memory).filter(Memory.user_id == user.id, Memory.state != MemoryState.deleted, Memory.state != MemoryState.archived).all()
    # Get all categories from memories
    categories = [category for memory in memories for category in memory.categories]
    # Get unique categories
    unique_categories = list(set(categories))

    return {
        "categories": unique_categories,
        "total": len(unique_categories)
    }


class CreateMemoryRequest(BaseModel):
    user_id: str
    text: str
    metadata: dict = {}
    infer: bool = True
    app: str = "openmemory"


# Create new memory
@router.post("/")
async def create_memory(
    request: CreateMemoryRequest,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.user_id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Get or create app
    app_obj = db.query(App).filter(App.name == request.app,
                                   App.owner_id == user.id).first()
    if not app_obj:
        app_obj = App(name=request.app, owner_id=user.id)
        db.add(app_obj)
        db.commit()
        db.refresh(app_obj)

    # Check if app is active
    if not app_obj.is_active:
        raise HTTPException(status_code=403, detail=f"App {request.app} is currently paused on OpenMemory. Cannot create new memories.")

    # Log what we're about to do
    logging.info(f"Creating memory for user_id: {request.user_id} with app: {request.app}")
    
    # Try to get memory client safely
    try:
        memory_client = get_memory_client()
        if not memory_client:
            raise Exception("Memory client is not available")
    except Exception as client_error:
        logging.warning(f"Memory client unavailable: {client_error}. Creating memory in database only.")
        # Return a json response with the error
        return {
            "error": str(client_error)
        }

    # Try to save to Qdrant via memory_client
    try:
        qdrant_response = memory_client.add(
            request.text,
            user_id=request.user_id,  # Use string user_id to match search
            metadata={
                "source_app": "openmemory",
                "mcp_client": request.app,
            },
            infer=request.infer
        )
        
        # Log the response for debugging
        logging.info(f"Qdrant response: {qdrant_response}")
        
        # Process Qdrant response
        if isinstance(qdrant_response, dict) and 'results' in qdrant_response:
            created_memories = []
            
            for result in qdrant_response['results']:
                if result['event'] == 'ADD':
                    # Get the Qdrant-generated ID
                    memory_id = UUID(result['id'])
                    
                    # Check if memory already exists
                    existing_memory = db.query(Memory).filter(Memory.id == memory_id).first()
                    old_content = None
                    
                    if existing_memory:
                        # Update existing memory
                        old_content = existing_memory.content
                        existing_memory.state = MemoryState.active
                        existing_memory.content = result['memory']
                        memory = existing_memory
                        content_event = "UPDATE"
                    else:
                        # Create memory with the EXACT SAME ID from Qdrant
                        memory = Memory(
                            id=memory_id,  # Use the same ID that Qdrant generated
                            user_id=user.id,
                            app_id=app_obj.id,
                            content=result['memory'],
                            metadata_=request.metadata,
                            state=MemoryState.active
                        )
                        db.add(memory)
                        content_event = "ADD"
                    
                    # Create content change history
                    db.add(MemoryHistory(
                        memory_id=memory_id,
                        event=content_event,
                        old_memory=old_content,
                        new_memory=result['memory'],
                    ))
                    
                    # Create status history entry
                    history = MemoryStatusHistory(
                        memory_id=memory_id,
                        changed_by=user.id,
                        old_state=MemoryState.deleted if existing_memory else MemoryState.deleted,
                        new_state=MemoryState.active
                    )
                    db.add(history)
                    
                    created_memories.append(memory)
            
            # Commit all changes at once
            if created_memories:
                db.commit()
                for memory in created_memories:
                    db.refresh(memory)
                
                # Return the first memory (for API compatibility)
                # but all memories are now saved to the database
                return created_memories[0]
    except Exception as qdrant_error:
        logging.warning(f"Qdrant operation failed: {qdrant_error}.")
        # Return a json response with the error
        return {
            "error": str(qdrant_error)
        }




# Get memory by ID
@router.get("/{memory_id}")
async def get_memory(
    memory_id: UUID,
    db: Session = Depends(get_db)
):
    memory = get_memory_or_404(db, memory_id)
    return {
        "id": memory.id,
        "text": memory.content,
        "created_at": int(memory.created_at.timestamp()),
        "state": memory.state.value,
        "app_id": memory.app_id,
        "app_name": memory.app.name if memory.app else None,
        "categories": [category.name for category in memory.categories],
        "metadata_": memory.metadata_
    }


class DeleteMemoriesRequest(BaseModel):
    memory_ids: List[UUID]
    user_id: str

# Delete multiple memories
@router.delete("/")
async def delete_memories(
    request: DeleteMemoriesRequest,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.user_id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get memory client to delete from vector store
    try:
        memory_client = get_memory_client()
        if not memory_client:
            raise HTTPException(
                status_code=503,
                detail="Memory client is not available"
            )
    except HTTPException:
        raise
    except Exception as client_error:
        logging.error(f"Memory client initialization failed: {client_error}")
        raise HTTPException(
            status_code=503,
            detail=f"Memory service unavailable: {str(client_error)}"
        )

    # Delete from vector store then mark as deleted in database
    for memory_id in request.memory_ids:
        try:
            memory_client.delete(str(memory_id))
        except Exception as delete_error:
            logging.warning(f"Failed to delete memory {memory_id} from vector store: {delete_error}")

        update_memory_state(db, memory_id, MemoryState.deleted, user.id)

    return {"message": f"Successfully deleted {len(request.memory_ids)} memories"}


# Archive memories
@router.post("/actions/archive")
async def archive_memories(
    memory_ids: List[UUID],
    user_id: UUID,
    db: Session = Depends(get_db)
):
    for memory_id in memory_ids:
        update_memory_state(db, memory_id, MemoryState.archived, user_id)
    return {"message": f"Successfully archived {len(memory_ids)} memories"}


class PauseMemoriesRequest(BaseModel):
    memory_ids: Optional[List[UUID]] = None
    category_ids: Optional[List[UUID]] = None
    app_id: Optional[UUID] = None
    all_for_app: bool = False
    global_pause: bool = False
    state: Optional[MemoryState] = None
    user_id: str

# Pause access to memories
@router.post("/actions/pause")
async def pause_memories(
    request: PauseMemoriesRequest,
    db: Session = Depends(get_db)
):
    
    global_pause = request.global_pause
    all_for_app = request.all_for_app
    app_id = request.app_id
    memory_ids = request.memory_ids
    category_ids = request.category_ids
    state = request.state or MemoryState.paused

    user = db.query(User).filter(User.user_id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_id = user.id
    
    if global_pause:
        # Pause all memories
        memories = db.query(Memory).filter(
            Memory.state != MemoryState.deleted,
            Memory.state != MemoryState.archived
        ).all()
        for memory in memories:
            update_memory_state(db, memory.id, state, user_id)
        return {"message": "Successfully paused all memories"}

    if app_id:
        # Pause all memories for an app
        memories = db.query(Memory).filter(
            Memory.app_id == app_id,
            Memory.user_id == user.id,
            Memory.state != MemoryState.deleted,
            Memory.state != MemoryState.archived
        ).all()
        for memory in memories:
            update_memory_state(db, memory.id, state, user_id)
        return {"message": f"Successfully paused all memories for app {app_id}"}
    
    if all_for_app and memory_ids:
        # Pause all memories for an app
        memories = db.query(Memory).filter(
            Memory.user_id == user.id,
            Memory.state != MemoryState.deleted,
            Memory.id.in_(memory_ids)
        ).all()
        for memory in memories:
            update_memory_state(db, memory.id, state, user_id)
        return {"message": "Successfully paused all memories"}

    if memory_ids:
        # Pause specific memories
        for memory_id in memory_ids:
            update_memory_state(db, memory_id, state, user_id)
        return {"message": f"Successfully paused {len(memory_ids)} memories"}

    if category_ids:
        # Pause memories by category
        memories = db.query(Memory).join(Memory.categories).filter(
            Category.id.in_(category_ids),
            Memory.state != MemoryState.deleted,
            Memory.state != MemoryState.archived
        ).all()
        for memory in memories:
            update_memory_state(db, memory.id, state, user_id)
        return {"message": f"Successfully paused memories in {len(category_ids)} categories"}

    raise HTTPException(status_code=400, detail="Invalid pause request parameters")


# Get memory access logs
@router.get("/{memory_id}/access-log")
async def get_memory_access_log(
    memory_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(MemoryAccessLog).filter(MemoryAccessLog.memory_id == memory_id)
    total = query.count()
    logs = query.order_by(MemoryAccessLog.accessed_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # Get app name
    for log in logs:
        app = db.query(App).filter(App.id == log.app_id).first()
        log.app_name = app.name if app else None

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "logs": logs
    }


class UpdateMemoryRequest(BaseModel):
    memory_content: str
    user_id: str

# Update a memory
@router.put("/{memory_id}")
async def update_memory(
    memory_id: UUID,
    request: UpdateMemoryRequest,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.user_id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    memory = get_memory_or_404(db, memory_id)
    old_content = memory.content
    memory.content = request.memory_content
    db.add(MemoryHistory(
        memory_id=memory_id,
        event="UPDATE",
        old_memory=old_content,
        new_memory=request.memory_content,
    ))
    db.commit()
    db.refresh(memory)
    return memory

class FilterMemoriesRequest(BaseModel):
    user_id: str
    page: int = 1
    size: int = 10
    search_query: Optional[str] = None
    app_ids: Optional[List[UUID]] = None
    category_ids: Optional[List[UUID]] = None
    sort_column: Optional[str] = None
    sort_direction: Optional[str] = None
    from_date: Optional[int] = None
    to_date: Optional[int] = None
    show_archived: Optional[bool] = False
    feedback_statuses: Optional[List[str]] = None

@router.post("/filter", response_model=Page[MemoryResponse])
async def filter_memories(
    request: FilterMemoriesRequest,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.user_id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Build base query
    query = db.query(Memory).filter(
        Memory.user_id == user.id,
        Memory.state != MemoryState.deleted,
    )

    # Filter archived memories based on show_archived parameter
    if not request.show_archived:
        query = query.filter(Memory.state != MemoryState.archived)

    # Apply search filter
    if request.search_query:
        query = query.filter(Memory.content.ilike(f"%{request.search_query}%"))

    # Apply app filter
    if request.app_ids:
        query = query.filter(Memory.app_id.in_(request.app_ids))

    # Add joins for app and categories
    query = query.outerjoin(App, Memory.app_id == App.id)

    # Apply category filter
    if request.category_ids:
        query = query.join(Memory.categories).filter(Category.id.in_(request.category_ids))
    else:
        query = query.outerjoin(Memory.categories)

    # Apply date filters
    if request.from_date:
        from_datetime = datetime.fromtimestamp(request.from_date, tz=UTC)
        query = query.filter(Memory.created_at >= from_datetime)

    if request.to_date:
        to_datetime = datetime.fromtimestamp(request.to_date, tz=UTC)
        query = query.filter(Memory.created_at <= to_datetime)

    if request.feedback_statuses:
        has_unreviewed = any(s == "unreviewed" for s in request.feedback_statuses)
        valid = [FeedbackStatus(s) for s in request.feedback_statuses if s != "unreviewed"]

        latest_sub = db.query(
            MemoryFeedback.memory_id,
            func.max(MemoryFeedback.created_at).label("max_created_at"),
        ).group_by(MemoryFeedback.memory_id).subquery()

        memory_ids_with_feedback = [r[0] for r in db.query(MemoryFeedback.memory_id).join(
            latest_sub,
            (MemoryFeedback.memory_id == latest_sub.c.memory_id)
            & (MemoryFeedback.created_at == latest_sub.c.max_created_at),
        ).filter(
            MemoryFeedback.status.in_(valid) if valid else False
        ).all()]

        if has_unreviewed:
            all_fb_memory_ids = {r[0] for r in db.query(MemoryFeedback.memory_id).distinct().all()}
            query = query.filter(
                (Memory.id.in_(memory_ids_with_feedback))
                | (~Memory.id.in_(list(all_fb_memory_ids)))
            )
        else:
            query = query.filter(Memory.id.in_(memory_ids_with_feedback))

    # Apply sorting
    if request.sort_column and request.sort_direction:
        sort_direction = request.sort_direction.lower()
        if sort_direction not in ['asc', 'desc']:
            raise HTTPException(status_code=400, detail="Invalid sort direction")

        sort_mapping = {
            'memory': Memory.content,
            'app_name': App.name,
            'created_at': Memory.created_at
        }

        if request.sort_column not in sort_mapping:
            raise HTTPException(status_code=400, detail="Invalid sort column")

        sort_field = sort_mapping[request.sort_column]
        if sort_direction == 'desc':
            query = query.order_by(sort_field.desc())
        else:
            query = query.order_by(sort_field.asc())
    else:
        # Default sorting
        query = query.order_by(Memory.created_at.desc())

    # Add eager loading for categories and make the query distinct
    query = query.options(
        joinedload(Memory.categories)
    ).distinct(Memory.id)

    all_memories = query.all()
    fb_map = _batch_feedback_statuses(db, [m.id for m in all_memories])

    def _build_response(items):
        return [
            MemoryResponse(
                id=memory.id,
                content=memory.content,
                created_at=memory.created_at,
                state=memory.state.value,
                app_id=memory.app_id,
                app_name=memory.app.name if memory.app else None,
                categories=[category.name for category in memory.categories],
                metadata_=memory.metadata_,
                feedback_status=fb_map.get(str(memory.id)),
            )
            for memory in items
        ]

    return sqlalchemy_paginate(
        query,
        Params(page=request.page, size=request.size),
        transformer=_build_response
    )


@router.get("/{memory_id}/related", response_model=Page[MemoryResponse])
async def get_related_memories(
    memory_id: UUID,
    user_id: str,
    params: Params = Depends(),
    db: Session = Depends(get_db)
):
    # Validate user
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get the source memory
    memory = get_memory_or_404(db, memory_id)
    
    # Extract category IDs from the source memory
    category_ids = [category.id for category in memory.categories]
    
    if not category_ids:
        return Page.create([], total=0, params=params)
    
    # Build query for related memories
    query = db.query(Memory).distinct(Memory.id).filter(
        Memory.user_id == user.id,
        Memory.id != memory_id,
        Memory.state != MemoryState.deleted
    ).join(Memory.categories).filter(
        Category.id.in_(category_ids)
    ).options(
        joinedload(Memory.categories),
        joinedload(Memory.app)
    ).order_by(
        func.count(Category.id).desc(),
        Memory.created_at.desc()
    ).group_by(Memory.id)
    
    params = Params(page=params.page, size=5)

    all_related = query.all()
    fb_map = _batch_feedback_statuses(db, [m.id for m in all_related])

    return sqlalchemy_paginate(
        query,
        params,
        transformer=lambda items: [
            MemoryResponse(
                id=memory.id,
                content=memory.content,
                created_at=memory.created_at,
                state=memory.state.value,
                app_id=memory.app_id,
                app_name=memory.app.name if memory.app else None,
                categories=[category.name for category in memory.categories],
                metadata_=memory.metadata_,
                feedback_status=fb_map.get(str(memory.id)),
            )
            for memory in items
        ]
    )


def _validate_feedback_status(status: str) -> FeedbackStatus:
    """Validate and convert string status to FeedbackStatus enum."""
    try:
        return FeedbackStatus(status)
    except ValueError:
        valid = ", ".join(sorted(s.value for s in FeedbackStatus))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid feedback status '{status}'. Must be one of: {valid}",
        )


def _get_current_feedback_status(db: Session, memory_id: UUID) -> Optional[FeedbackStatus]:
    """Get the latest feedback status for a memory (or None if never reviewed)."""
    latest = (
        db.query(MemoryFeedback)
        .filter(MemoryFeedback.memory_id == memory_id)
        .order_by(MemoryFeedback.created_at.desc())
        .first()
    )
    return latest.status if latest else None


# Submit feedback on a memory
@router.post("/{memory_id}/feedback")
async def submit_feedback(
    memory_id: UUID,
    request: FeedbackSubmitRequest,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    memory = get_memory_or_404(db, memory_id)

    status_enum = _validate_feedback_status(request.status)
    previous_status = _get_current_feedback_status(db, memory_id)

    linked_history_uuid = None
    if request.linked_history_id:
        try:
            linked_history_uuid = UUID(request.linked_history_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="linked_history_id must be a valid UUID")

    reviewer_uuid = None
    if request.reviewer_id:
        reviewer = db.query(User).filter(User.user_id == request.reviewer_id).first()
        if not reviewer:
            raise HTTPException(status_code=404, detail="Reviewer user not found")
        reviewer_uuid = reviewer.id

    feedback_record = MemoryFeedback(
        memory_id=memory_id,
        user_id=user.id,
        status=status_enum,
        reason=request.reason,
        reviewer_id=reviewer_uuid,
        previous_status=previous_status,
        linked_history_id=linked_history_uuid,
    )
    db.add(feedback_record)
    db.commit()
    db.refresh(feedback_record)

    return {
        "message": "Feedback submitted successfully",
        "feedback": FeedbackRecordResponse(
            id=feedback_record.id,
            memory_id=feedback_record.memory_id,
            status=feedback_record.status.value,
            reason=feedback_record.reason,
            reviewer_id=request.reviewer_id,
            previous_status=feedback_record.previous_status.value if feedback_record.previous_status else None,
            linked_history_id=str(feedback_record.linked_history_id) if feedback_record.linked_history_id else None,
            created_at=feedback_record.created_at,
        ),
    }


# Get all feedback records for a memory
@router.get("/{memory_id}/feedback", response_model=FeedbackListResponse)
async def get_memory_feedback(
    memory_id: UUID,
    user_id: str,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    memory = get_memory_or_404(db, memory_id)

    records = (
        db.query(MemoryFeedback)
        .filter(MemoryFeedback.memory_id == memory_id)
        .order_by(MemoryFeedback.created_at.asc())
        .all()
    )

    # Build a reviewer-id -> reviewer-user-id map for the response
    reviewer_ids = {r.reviewer_id for r in records if r.reviewer_id}
    reviewer_map = {}
    if reviewer_ids:
        reviewers = db.query(User).filter(User.id.in_(reviewer_ids)).all()
        reviewer_map = {r.id: r.user_id for r in reviewers}

    feedback_list = [
        FeedbackRecordResponse(
            id=r.id,
            memory_id=r.memory_id,
            status=r.status.value,
            reason=r.reason,
            reviewer_id=reviewer_map.get(r.reviewer_id) if r.reviewer_id else None,
            previous_status=r.previous_status.value if r.previous_status else None,
            linked_history_id=str(r.linked_history_id) if r.linked_history_id else None,
            created_at=r.created_at,
        )
        for r in records
    ]

    return FeedbackListResponse(memory_id=memory_id, feedback=feedback_list)


# Get all content history records for a memory (ADD / UPDATE / DELETE)
@router.get("/{memory_id}/history")
async def get_memory_history(
    memory_id: UUID,
    user_id: str,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    memory = get_memory_or_404(db, memory_id)

    records = (
        db.query(MemoryHistory)
        .filter(MemoryHistory.memory_id == memory_id)
        .order_by(MemoryHistory.created_at.asc())
        .all()
    )

    return {
        "memory_id": str(memory_id),
        "history": [
            MemoryHistoryResponse(
                id=r.id,
                memory_id=r.memory_id,
                event=r.event,
                old_memory=r.old_memory,
                new_memory=r.new_memory,
                metadata_=r.metadata_,
                created_at=r.created_at,
            )
            for r in records
        ],
    }


# List memory IDs filtered by feedback status — for the review queue in the dashboard
@router.post("/feedback/status")
async def list_memories_by_feedback_status(
    request: FeedbackByStatusRequest,
    db: Session = Depends(get_db),
):
    """
    Returns memory IDs whose *current* feedback status matches the requested filter.
    Each memory is represented by its latest feedback record, and we filter across those.
    Useful for building the dashboard's review queue (needs_review, etc.).
    """
    user = db.query(User).filter(User.user_id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    status_enum = _validate_feedback_status(request.status)

    # Subquery: pick the latest feedback per memory_id
    from sqlalchemy import and_ as sa_and_
    from sqlalchemy import tuple_ as sa_tuple_

    latest_created_subq = (
        db.query(
            MemoryFeedback.memory_id,
            func.max(MemoryFeedback.created_at).label("max_created"),
        )
        .filter(MemoryFeedback.memory_id.in_(
            db.query(Memory.id).filter(Memory.user_id == user.id).subquery()
        ))
        .group_by(MemoryFeedback.memory_id)
        .subquery()
    )

    query = (
        db.query(MemoryFeedback)
        .join(
            latest_created_subq,
            sa_and_(
                MemoryFeedback.memory_id == latest_created_subq.c.memory_id,
                MemoryFeedback.created_at == latest_created_subq.c.max_created,
            ),
        )
        .filter(MemoryFeedback.status == status_enum)
    )

    if request.app_id:
        query = query.filter(
            MemoryFeedback.memory_id.in_(
                db.query(Memory.id).filter(Memory.app_id == request.app_id).subquery()
            )
        )

    records = query.all()

    # Also attach memory content preview, app_id, app_name so the dashboard can render the queue directly
    result_items = []
    for r in records:
        memory = db.query(Memory).options(joinedload(Memory.app)).filter(Memory.id == r.memory_id).first()
        if memory:
            result_items.append({
                "memory_id": str(r.memory_id),
                "content_preview": (memory.content[:140] + "...") if len(memory.content) > 140 else memory.content,
                "app_id": str(memory.app_id) if memory.app_id else None,
                "app_name": memory.app.name if memory.app else None,
                "created_at": int(r.created_at.timestamp()),
                "reviewer_id": None,
            })

    return {
        "status": request.status,
        "total": len(result_items),
        "items": result_items,
    }