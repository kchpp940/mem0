"use client";

import { useEffect, useState } from "react";
import { Clock, Trash2 } from "lucide-react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/shared/data-table";
import { TableSkeleton } from "@/components/shared/table-skeleton";
import { EmptyState } from "@/components/self-hosted/empty-state";
import DeleteConfirmationModal from "@/components/ui/delete-confirmation-modal";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { UpgradeBanner } from "@/components/self-hosted/upgrade-banner";
import { toast } from "@/components/ui/use-toast";
import { getErrorMessage } from "@/lib/error-message";
import { api } from "@/utils/api";
import { MEMORY_ENDPOINTS } from "@/utils/api-endpoints";
import { useApiQuery } from "@/hooks/use-api-query";
import { Memory } from "@/types/api";

const PAGE_SIZE = 20;

const TTL_STATE_OPTIONS = [
  { value: "all", label: "All memories" },
  { value: "active", label: "Active" },
  { value: "expiring_soon", label: "Expiring soon" },
  { value: "expired", label: "Expired" },
  { value: "permanent", label: "Permanent" },
] as const;

type TtlFilter = (typeof TTL_STATE_OPTIONS)[number]["value"];

function ttlBadgeClass(state: string | null | undefined): string {
  switch (state) {
    case "active":
      return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-500/25";
    case "expiring_soon":
      return "bg-amber-500/15 text-amber-700 dark:text-amber-400 hover:bg-amber-500/25";
    case "expired":
      return "bg-rose-500/15 text-rose-700 dark:text-rose-400 hover:bg-rose-500/25";
    case "permanent":
      return "bg-indigo-500/15 text-indigo-700 dark:text-indigo-400 hover:bg-indigo-500/25";
    default:
      return "bg-slate-500/15 text-slate-700 dark:text-slate-400 hover:bg-slate-500/25";
  }
}

function ttlSourceLabel(source: string | null | undefined): string {
  switch (source) {
    case "request":
      return "Per request";
    case "category":
      return "Category policy";
    case "user":
      return "User policy";
    case "agent":
      return "Agent policy";
    case "workspace":
      return "Workspace policy";
    case "default":
      return "Default policy";
    default:
      return source ?? "--";
  }
}

export default function MemoriesPage() {
  const [userId, setUserId] = useState("");
  const [appliedUserId, setAppliedUserId] = useState("");
  const [ttlFilter, setTtlFilter] = useState<TtlFilter>("all");
  const [appliedTtlFilter, setAppliedTtlFilter] = useState<TtlFilter>("all");
  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null);
  const [memoryToDelete, setMemoryToDelete] = useState<Memory | null>(null);
  const [page, setPage] = useState(0);
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";

  const {
    data: memories = [],
    isLoading,
    refetch,
  } = useApiQuery<Memory[]>(
    async () => {
      const params: Record<string, string> = {};
      if (appliedUserId.trim()) params.user_id = appliedUserId.trim();
      if (appliedTtlFilter !== "all") params.ttl_state = appliedTtlFilter;
      const res = await api.get(MEMORY_ENDPOINTS.BASE, { params });
      const raw = res.data?.results ?? res.data ?? [];
      return Array.isArray(raw) ? raw : [];
    },
    { errorToast: "Failed to load memories", initialData: [] },
  );

  // Re-fetch whenever applied filters change
  useEffect(() => {
    void refetch();
  }, [appliedUserId, appliedTtlFilter, refetch]);

  const totalPages = Math.ceil(memories.length / PAGE_SIZE);
  const paginatedMemories = memories.slice(
    page * PAGE_SIZE,
    (page + 1) * PAGE_SIZE,
  );

  const handleDelete = async () => {
    if (!memoryToDelete) return;
    try {
      await api.delete(MEMORY_ENDPOINTS.BY_ID(memoryToDelete.id));
      toast({ title: "Memory deleted", variant: "success" });
      if (selectedMemory?.id === memoryToDelete.id) setSelectedMemory(null);
      setMemoryToDelete(null);
      void refetch();
    } catch (error) {
      toast({
        title: "Failed to delete memory",
        description: getErrorMessage(error),
        variant: "destructive",
      });
    }
  };

  const columns = [
    {
      key: "memory" as keyof Memory,
      label: "Content",
      width: 360,
      render: (value: string) => (
        <span className="line-clamp-2 text-sm">{value}</span>
      ),
    },
    { key: "user_id" as keyof Memory, label: "User", width: 90 },
    { key: "agent_id" as keyof Memory, label: "Agent", width: 90 },
    {
      key: "ttl_state" as keyof Memory,
      label: "TTL State",
      width: 120,
      render: (value: string | null | undefined, row: Memory) => (
        <Badge
          variant="secondary"
          className={`font-normal ${ttlBadgeClass(value)}`}
        >
          <Clock className="size-3 mr-1 opacity-70" />
          {value ?? "permanent"}
        </Badge>
      ),
    },
    {
      key: "created_at" as keyof Memory,
      label: "Created",
      width: 110,
      render: (value: string) =>
        value ? format(new Date(value), "MMM d, yyyy") : "--",
    },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold font-fustat">Memories</h1>

      {memories.length >= 1000 && (
        <UpgradeBanner
          id="memories-1k"
          message="1,000+ memories stored. Categories can help organize them."
          ctaLabel="Explore Cloud"
          ctaUrl="https://app.mem0.ai?utm_source=oss&utm_medium=dashboard-memories"
          variant="cloud"
        />
      )}

      <div className="flex flex-wrap gap-3">
        <Input
          placeholder="Filter by User ID (optional)"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              setPage(0);
              setAppliedUserId(userId);
            }
          }}
          className="w-64"
        />
        <Select
          value={ttlFilter}
          onValueChange={(v) => {
            const nv = v as TtlFilter;
            setTtlFilter(nv);
            setAppliedTtlFilter(nv);
            setPage(0);
          }}
        >
          <SelectTrigger className="w-52">
            <SelectValue placeholder="Filter by TTL state" />
          </SelectTrigger>
          <SelectContent>
            {TTL_STATE_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <TableSkeleton rows={5} columns={5} />
      ) : memories.length === 0 ? (
        <EmptyState
          title={
            appliedTtlFilter !== "all"
              ? `No ${appliedTtlFilter} memories`
              : "No memories yet"
          }
          description="Create your first memory by sending a POST /memories request."
        >
          <pre className="text-xs text-left bg-surface-default-secondary p-3 rounded font-mono overflow-x-auto mt-3 max-w-lg">
            {`curl -X POST ${apiUrl}/memories \\
  -H "X-API-Key: <your-key>" \\
  -H "Content-Type: application/json" \\
  -d '{"messages": [{"role": "user", "content": "I like hiking"}], "user_id": "alice"}'`}
          </pre>
          <a
            href="https://docs.mem0.ai/open-source/features/rest-api#memory-operations"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-onSurface-default-tertiary underline underline-offset-4 hover:text-onSurface-default-primary mt-2"
          >
            REST API reference
          </a>
        </EmptyState>
      ) : (
        <>
          <Card className="border-memBorder-primary overflow-hidden">
            <DataTable
              data={paginatedMemories}
              columns={columns}
              getRowKey={(row) => row.id}
              onRowClick={(row) => setSelectedMemory(row)}
              getRowClassName={(row) =>
                selectedMemory?.id === row.id
                  ? "bg-surface-default-tertiary"
                  : undefined
              }
            />
          </Card>
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-onSurface-default-tertiary">
              <span>
                {page * PAGE_SIZE + 1}–
                {Math.min((page + 1) * PAGE_SIZE, memories.length)} of{" "}
                {memories.length}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages - 1}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      <Sheet
        open={!!selectedMemory}
        onOpenChange={(open) => {
          if (!open) setSelectedMemory(null);
        }}
      >
        <SheetContent className="sm:max-w-md">
          <SheetHeader>
            <SheetTitle>Memory Detail</SheetTitle>
            <SheetDescription className="sr-only">
              View memory content and metadata
            </SheetDescription>
          </SheetHeader>
          {selectedMemory && (
            <div className="mt-6 space-y-4">
              <div className="space-y-1">
                <Label className="text-xs text-onSurface-default-tertiary">
                  Content
                </Label>
                <p className="text-sm">{selectedMemory.memory}</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs text-onSurface-default-tertiary">
                    ID
                  </Label>
                  <p className="text-xs font-mono break-all">
                    {selectedMemory.id}
                  </p>
                </div>
                {selectedMemory.user_id && (
                  <div className="space-y-1">
                    <Label className="text-xs text-onSurface-default-tertiary">
                      User
                    </Label>
                    <p className="text-sm">{selectedMemory.user_id}</p>
                  </div>
                )}
                {selectedMemory.agent_id && (
                  <div className="space-y-1">
                    <Label className="text-xs text-onSurface-default-tertiary">
                      Agent
                    </Label>
                    <p className="text-sm">{selectedMemory.agent_id}</p>
                  </div>
                )}
                <div className="space-y-1">
                  <Label className="text-xs text-onSurface-default-tertiary">
                    TTL State
                  </Label>
                  <div>
                    <Badge
                      variant="secondary"
                      className={`font-normal ${ttlBadgeClass(
                        selectedMemory.ttl_state,
                      )}`}
                    >
                      <Clock className="size-3 mr-1 opacity-70" />
                      {selectedMemory.ttl_state ?? "permanent"}
                    </Badge>
                  </div>
                </div>
                {selectedMemory.expires_at && (
                  <div className="space-y-1">
                    <Label className="text-xs text-onSurface-default-tertiary">
                      Expires At
                    </Label>
                    <p className="text-sm">
                      {new Date(selectedMemory.expires_at).toLocaleString()}
                    </p>
                  </div>
                )}
                {selectedMemory.ttl_source && (
                  <div className="space-y-1">
                    <Label className="text-xs text-onSurface-default-tertiary">
                      TTL Source
                    </Label>
                    <p className="text-sm">
                      {ttlSourceLabel(selectedMemory.ttl_source)}
                    </p>
                  </div>
                )}
                {selectedMemory.created_at && (
                  <div className="space-y-1">
                    <Label className="text-xs text-onSurface-default-tertiary">
                      Created
                    </Label>
                    <p className="text-sm">
                      {new Date(selectedMemory.created_at).toLocaleString()}
                    </p>
                  </div>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                className="text-onSurface-danger-primary"
                onClick={() => setMemoryToDelete(selectedMemory)}
              >
                <Trash2 className="size-3.5 mr-1" />
                Delete memory
              </Button>
            </div>
          )}
        </SheetContent>
      </Sheet>

      <DeleteConfirmationModal
        isOpen={!!memoryToDelete}
        onClose={() => setMemoryToDelete(null)}
        onConfirm={handleDelete}
        title="Delete memory"
        description="This memory will be permanently removed. This cannot be undone."
        itemName={memoryToDelete?.id ?? ""}
        confirmButtonText="Delete"
      />
    </div>
  );
}
