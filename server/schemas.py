from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    message: str


class ImportMemoryItem(BaseModel):
    memory: Optional[str] = Field(None, description="Memory content (alias: text, content)")
    text: Optional[str] = Field(None, description="Memory content (alias for memory)")
    content: Optional[str] = Field(None, description="Memory content (alias for memory)")
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    app_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    categories: Optional[List[str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    feedback: Optional[str] = None
    feedback_reason: Optional[str] = None
    immutable: Optional[bool] = False
    infer: Optional[bool] = True

    def get_content(self) -> Optional[str]:
        return self.memory or self.text or self.content


class BatchImportRequest(BaseModel):
    memories: List[ImportMemoryItem] = Field(..., description="List of memory items to import")
    cursor: Optional[int] = Field(0, description="Starting index for batch processing (for resumption)")
    batch_size: Optional[int] = Field(100, description="Number of items to process in this batch")
    infer: Optional[bool] = Field(True, description="Whether to infer facts from memory content")


class ImportResultItem(BaseModel):
    index: int = Field(..., description="Original index in the input list")
    success: bool = Field(..., description="Whether the import succeeded")
    memory_id: Optional[str] = Field(None, description="ID of the created memory (on success)")
    memory: Optional[str] = Field(None, description="The memory content")
    error: Optional[str] = Field(None, description="Error message (on failure)")


class BatchImportResponse(BaseModel):
    batch_id: str = Field(..., description="Unique identifier for this batch")
    total: int = Field(..., description="Total items in the full import set")
    processed: int = Field(..., description="Total items processed so far")
    success_count: int = Field(..., description="Number of successfully imported items")
    failed_count: int = Field(..., description="Number of failed items")
    cursor: int = Field(..., description="Next cursor position for resumption")
    completed: bool = Field(..., description="Whether all items have been processed")
    successful: List[ImportResultItem] = Field(default_factory=list, description="Successful items in this batch")
    failed: List[ImportResultItem] = Field(default_factory=list, description="Failed items in this batch")


class BatchStatusResponse(BaseModel):
    batch_id: str = Field(..., description="Batch identifier")
    total: int = Field(..., description="Total items in batch")
    processed: int = Field(..., description="Items processed")
    success_count: int = Field(..., description="Successful imports")
    failed_count: int = Field(..., description="Failed imports")
    completed: bool = Field(..., description="Processing complete")
    created_at: datetime = Field(..., description="Batch creation time")
    updated_at: datetime = Field(..., description="Last update time")


class ExportMemoryItem(BaseModel):
    id: str = Field(..., description="Memory ID")
    memory: str = Field(..., description="Memory content")
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    app_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    categories: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    feedback: Optional[str] = None
    feedback_reason: Optional[str] = None


class ExportRequest(BaseModel):
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    app_id: Optional[str] = None
    category: Optional[str] = None
    after: Optional[str] = None
    before: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    page_size: Optional[int] = Field(1000, description="Page size for streaming export")
