"use client";

import { useEffect, useState, useMemo } from "react";
import { useFeedbackApi, FeedbackRecord, FeedbackStatusType } from "@/hooks/useFeedbackApi";
import { useMemoriesApi, MemoryHistoryRecord } from "@/hooks/useMemoriesApi";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  Eye,
  MessageSquare,
  ArrowRight,
  Plus,
  Pencil,
  Trash2,
  CornerDownRight,
} from "lucide-react";
import { useDispatch } from "react-redux";
import { updateMemoryFeedbackStatus } from "@/store/memoriesSlice";

const STATUS_CONFIG: Record<FeedbackStatusType, { label: string; icon: React.ReactNode; color: string; bg: string; hoverBg: string }> = {
  needs_review: {
    label: "Needs Review",
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
    color: "text-amber-400",
    bg: "bg-amber-400/10 border-amber-400/30",
    hoverBg: "hover:bg-amber-400/10",
  },
  incorrect: {
    label: "Incorrect",
    icon: <XCircle className="h-3.5 w-3.5" />,
    color: "text-red-400",
    bg: "bg-red-400/10 border-red-400/30",
    hoverBg: "hover:bg-red-400/10",
  },
  outdated: {
    label: "Outdated",
    icon: <Clock className="h-3.5 w-3.5" />,
    color: "text-orange-400",
    bg: "bg-orange-400/10 border-orange-400/30",
    hoverBg: "hover:bg-orange-400/10",
  },
  confirmed: {
    label: "Confirmed",
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    color: "text-emerald-400",
    bg: "bg-emerald-400/10 border-emerald-400/30",
    hoverBg: "hover:bg-emerald-400/10",
  },
  unreviewed: {
    label: "Unreviewed",
    icon: <Eye className="h-3.5 w-3.5" />,
    color: "text-zinc-400",
    bg: "bg-zinc-400/10 border-zinc-400/30",
    hoverBg: "hover:bg-zinc-400/10",
  },
};

const EVENT_ICON: Record<string, React.ReactNode> = {
  ADD: <Plus className="h-3.5 w-3.5" />,
  UPDATE: <Pencil className="h-3.5 w-3.5" />,
  DELETE: <Trash2 className="h-3.5 w-3.5" />,
};

const EVENT_LABEL: Record<string, { label: string; color: string; bg: string }> = {
  ADD: { label: "Created", color: "text-emerald-400", bg: "bg-emerald-400/10 border-emerald-400/30" },
  UPDATE: { label: "Updated", color: "text-blue-400", bg: "bg-blue-400/10 border-blue-400/30" },
  DELETE: { label: "Deleted", color: "text-red-400", bg: "bg-red-400/10 border-red-400/30" },
};

type TimelineItem =
  | { kind: "feedback"; record: FeedbackRecord; linkedHistory?: MemoryHistoryRecord }
  | { kind: "history"; record: MemoryHistoryRecord };

interface FeedbackPanelProps {
  memoryId: string;
}

export function FeedbackPanel({ memoryId }: FeedbackPanelProps) {
  const dispatch = useDispatch();
  const { submitFeedback, fetchFeedbackHistory, isLoading: fbLoading } = useFeedbackApi();
  const { fetchMemoryHistory } = useMemoriesApi();

  const [feedbackHistory, setFeedbackHistory] = useState<FeedbackRecord[]>([]);
  const [memoryHistory, setMemoryHistory] = useState<MemoryHistoryRecord[]>([]);
  const [currentStatus, setCurrentStatus] = useState<FeedbackStatusType>("unreviewed");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<FeedbackStatusType | null>(null);
  const [reason, setReason] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [combinedLoading, setCombinedLoading] = useState(true);

  useEffect(() => {
    const loadAll = async () => {
      if (!memoryId) return;
      setCombinedLoading(true);
      try {
        const [fb, hist] = await Promise.all([
          fetchFeedbackHistory(memoryId),
          fetchMemoryHistory(memoryId),
        ]);
        setFeedbackHistory(fb);
        setMemoryHistory(hist);
        if (fb.length > 0) {
          setCurrentStatus(fb[fb.length - 1].status);
        } else {
          setCurrentStatus("unreviewed");
        }
      } catch (err) {
        console.error("Failed to load feedback / history:", err);
      } finally {
        setCombinedLoading(false);
      }
    };
    loadAll();
  }, [memoryId, refreshKey]);

  const timeline = useMemo<TimelineItem[]>(() => {
    const histMap = new Map<string, MemoryHistoryRecord>();
    memoryHistory.forEach((h) => histMap.set(h.id, h));

    const items: TimelineItem[] = [];
    feedbackHistory.forEach((f) => {
      items.push({
        kind: "feedback",
        record: f,
        linkedHistory: f.linked_history_id ? histMap.get(f.linked_history_id) : undefined,
      });
    });
    memoryHistory.forEach((h) => {
      const alreadyLinked = items.some(
        (it) => it.kind === "feedback" && it.linkedHistory?.id === h.id
      );
      if (!alreadyLinked) {
        items.push({ kind: "history", record: h });
      }
    });

    return items.sort((a, b) => {
      const ta = a.kind === "feedback" ? a.record.created_at : a.record.created_at;
      const tb = b.kind === "feedback" ? b.record.created_at : b.record.created_at;
      return ta - tb;
    });
  }, [feedbackHistory, memoryHistory]);

  const handleStatusClick = (status: FeedbackStatusType) => {
    if (status === currentStatus) return;
    setPendingStatus(status);
    setReason("");
    setDialogOpen(true);
  };

  const handleSubmit = async () => {
    if (!pendingStatus) return;
    try {
      await submitFeedback(memoryId, pendingStatus, reason || undefined);
      dispatch(updateMemoryFeedbackStatus({ memoryId, feedbackStatus: pendingStatus }));
      setDialogOpen(false);
      setPendingStatus(null);
      setReason("");
      setRefreshKey((k) => k + 1);
    } catch (err) {
      console.error("Failed to submit feedback:", err);
    }
  };

  const statusOrder: FeedbackStatusType[] = ["confirmed", "needs_review", "incorrect", "outdated"];

  const formatTime = (ts: number) =>
    new Date(ts * 1000).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });

  const truncate = (s: string | null, n = 60) =>
    s ? (s.length > n ? s.slice(0, n) + "…" : s) : "";

  return (
    <div className="w-full max-w-md mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white pb-1">
      <div className="px-6 py-4 flex justify-between items-center bg-zinc-800 border-b border-zinc-800">
        <h2 className="font-semibold flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" />
          Feedback & History
        </h2>
        <Badge variant="outline" className={`${STATUS_CONFIG[currentStatus].bg} ${STATUS_CONFIG[currentStatus].color} border text-xs`}>
          {STATUS_CONFIG[currentStatus].icon}
          <span className="ml-1">{STATUS_CONFIG[currentStatus].label}</span>
        </Badge>
      </div>

      <div className="px-6 py-3 border-b border-zinc-800">
        <p className="text-xs text-zinc-500 mb-2">Set feedback status:</p>
        <div className="flex gap-2 flex-wrap">
          {statusOrder.map((status) => (
            <Button
              key={status}
              variant="outline"
              size="sm"
              disabled={fbLoading || status === currentStatus}
              onClick={() => handleStatusClick(status)}
              className={`text-xs border-zinc-700 ${
                status === currentStatus
                  ? `${STATUS_CONFIG[status].bg} ${STATUS_CONFIG[status].color} border`
                  : `text-zinc-400 ${STATUS_CONFIG[status].hoverBg}`
              }`}
            >
              {STATUS_CONFIG[status].icon}
              <span className="ml-1">{STATUS_CONFIG[status].label}</span>
            </Button>
          ))}
        </div>
      </div>

      <ScrollArea className="max-h-[420px]">
        <div className="px-6 py-4">
          {combinedLoading ? (
            <div className="text-center py-6 text-zinc-500 text-sm">Loading timeline…</div>
          ) : timeline.length === 0 ? (
            <div className="text-center py-6">
              <Eye className="h-8 w-8 text-zinc-600 mx-auto mb-2" />
              <p className="text-zinc-500 text-sm">No activity yet</p>
              <p className="text-zinc-600 text-xs mt-1">Changes and reviews will appear here</p>
            </div>
          ) : (
            <div className="space-y-0">
              {timeline.map((item, idx) => {
                if (item.kind === "feedback") {
                  const r = item.record;
                  const isLatest = idx === timeline.length - 1;
                  const cfg = STATUS_CONFIG[r.status];
                  return (
                    <div key={`fb-${r.id}`} className="relative pb-4">
                      <div className="flex items-start gap-3">
                        <div className="relative z-10 flex-shrink-0 mt-0.5">
                          <div className={`w-7 h-7 rounded-full flex items-center justify-center ${cfg.bg}`}>
                            {cfg.icon}
                          </div>
                        </div>
                        {idx < timeline.length - 1 && (
                          <div className="absolute left-3.5 top-7 bottom-0 w-px bg-zinc-800" />
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-sm font-medium ${cfg.color}`}>
                              {cfg.label}
                            </span>
                            {r.previous_status && (
                              <>
                                <ArrowRight className="h-3 w-3 text-zinc-600" />
                                <span className="text-xs text-zinc-500 line-through">
                                  {STATUS_CONFIG[r.previous_status]?.label || r.previous_status}
                                </span>
                              </>
                            )}
                            {isLatest && (
                              <Badge variant="secondary" className="bg-primary/10 text-primary text-[10px] px-1.5 py-0">
                                Current
                              </Badge>
                            )}
                          </div>
                          {r.reason && (
                            <p className="text-zinc-400 text-xs mt-1 leading-relaxed">
                              “{r.reason}”
                            </p>
                          )}
                          <div className="flex items-center gap-3 mt-1.5">
                            <span className="text-zinc-600 text-[11px]">{formatTime(r.created_at)}</span>
                            {r.reviewer_id && (
                              <span className="text-zinc-600 text-[11px]">
                                by {String(r.reviewer_id).slice(0, 8)}
                              </span>
                            )}
                          </div>
                          {item.linkedHistory && (
                            <div className="mt-2 ml-1 pl-3 border-l-2 border-zinc-700">
                              <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 mb-1">
                                <CornerDownRight className="h-3 w-3" />
                                Linked to {EVENT_LABEL[item.linkedHistory.event]?.label?.toLowerCase() || "event"}:
                              </div>
                              <div className="flex items-center gap-1.5 mb-1">
                                <Badge variant="outline" className={`${EVENT_LABEL[item.linkedHistory.event]?.bg || ""} ${EVENT_LABEL[item.linkedHistory.event]?.color || "text-zinc-400"} border text-[10px] px-1.5 py-0`}>
                                  {EVENT_ICON[item.linkedHistory.event] || <Eye className="h-3 w-3" />}
                                  <span className="ml-0.5">{item.linkedHistory.event}</span>
                                </Badge>
                                <span className="text-[11px] text-zinc-600">
                                  {formatTime(item.linkedHistory.created_at)}
                                </span>
                              </div>
                              {item.linkedHistory.event === "UPDATE" ? (
                                <div className="space-y-1 text-[11px]">
                                  <div>
                                    <span className="text-zinc-500">Before: </span>
                                    <span className="text-red-300/80 line-through">{truncate(item.linkedHistory.old_memory)}</span>
                                  </div>
                                  <div>
                                    <span className="text-zinc-500">After: </span>
                                    <span className="text-emerald-300/80">{truncate(item.linkedHistory.new_memory)}</span>
                                  </div>
                                </div>
                              ) : item.linkedHistory.event === "ADD" ? (
                                <p className="text-[11px] text-zinc-300/80">
                                  {truncate(item.linkedHistory.new_memory)}
                                </p>
                              ) : item.linkedHistory.event === "DELETE" ? (
                                <p className="text-[11px] text-red-300/80 line-through">
                                  {truncate(item.linkedHistory.old_memory)}
                                </p>
                              ) : null}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                } else {
                  const h = item.record;
                  const cfg = EVENT_LABEL[h.event] || { label: h.event, color: "text-zinc-300", bg: "bg-zinc-700" };
                  return (
                    <div key={`hist-${h.id}`} className="relative pb-4">
                      <div className="flex items-start gap-3">
                        <div className="relative z-10 flex-shrink-0 mt-0.5">
                          <div className={`w-7 h-7 rounded-full flex items-center justify-center ${cfg.bg} border`}>
                            {EVENT_ICON[h.event] || <Eye className="h-3.5 w-3.5" />}
                          </div>
                        </div>
                        {idx < timeline.length - 1 && (
                          <div className="absolute left-3.5 top-7 bottom-0 w-px bg-zinc-800" />
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className={`text-sm font-medium ${cfg.color}`}>{cfg.label}</span>
                          </div>
                          {h.event === "UPDATE" ? (
                            <div className="space-y-1 mt-1 text-[11px]">
                              <div>
                                <span className="text-zinc-500">Before: </span>
                                <span className="text-red-300/80 line-through">{truncate(h.old_memory)}</span>
                              </div>
                              <div>
                                <span className="text-zinc-500">After: </span>
                                <span className="text-emerald-300/80">{truncate(h.new_memory)}</span>
                              </div>
                            </div>
                          ) : h.event === "ADD" ? (
                            <p className="mt-1 text-[11px] text-zinc-300/80">{truncate(h.new_memory)}</p>
                          ) : h.event === "DELETE" ? (
                            <p className="mt-1 text-[11px] text-red-300/80 line-through">
                              {truncate(h.old_memory)}
                            </p>
                          ) : null}
                          <div className="flex items-center gap-3 mt-1.5">
                            <span className="text-zinc-600 text-[11px]">{formatTime(h.created_at)}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                }
              })}
            </div>
          )}
        </div>
      </ScrollArea>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="bg-zinc-900 border-zinc-800 text-white">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {pendingStatus && STATUS_CONFIG[pendingStatus]?.icon}
              Mark as {pendingStatus && STATUS_CONFIG[pendingStatus]?.label}
            </DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <label className="text-sm text-zinc-400 mb-2 block">Reason (optional)</label>
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={`Why is this memory being marked as ${pendingStatus && STATUS_CONFIG[pendingStatus]?.label?.toLowerCase()}?`}
              className="bg-zinc-800 border-zinc-700 text-white placeholder:text-zinc-500 min-h-[80px] resize-none"
            />
            {currentStatus !== "unreviewed" && (
              <p className="text-xs text-zinc-500 mt-2">
                Current status: <span className={STATUS_CONFIG[currentStatus]?.color}>{STATUS_CONFIG[currentStatus]?.label}</span>
                {" → "}
                <span className={STATUS_CONFIG[pendingStatus || "unreviewed"]?.color}>
                  {pendingStatus && STATUS_CONFIG[pendingStatus]?.label}
                </span>
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setDialogOpen(false)}
              className="text-zinc-400"
            >
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={fbLoading}
              className="bg-primary hover:bg-primary/90 text-white"
            >
              {fbLoading ? "Submitting..." : "Submit Feedback"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
