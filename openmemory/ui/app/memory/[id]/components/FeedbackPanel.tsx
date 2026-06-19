"use client";

import { useEffect, useState } from "react";
import { useFeedbackApi, FeedbackRecord, FeedbackStatusType } from "@/hooks/useFeedbackApi";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useDispatch } from "react-redux";
import { updateMemoryFeedbackStatus } from "@/store/memoriesSlice";
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
  Link2,
  History,
} from "lucide-react";

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

interface FeedbackPanelProps {
  memoryId: string;
}

export function FeedbackPanel({ memoryId }: FeedbackPanelProps) {
  const dispatch = useDispatch();
  const { submitFeedback, fetchFeedbackHistory, isLoading } = useFeedbackApi();
  const [feedbackHistory, setFeedbackHistory] = useState<FeedbackRecord[]>([]);
  const [currentStatus, setCurrentStatus] = useState<FeedbackStatusType>("unreviewed");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<FeedbackStatusType | null>(null);
  const [reason, setReason] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const loadFeedback = async () => {
      try {
        const records = await fetchFeedbackHistory(memoryId);
        setFeedbackHistory(records);
        if (records.length > 0) {
          setCurrentStatus(records[records.length - 1].status);
        } else {
          setCurrentStatus("unreviewed");
        }
      } catch (err) {
        console.error("Failed to load feedback history:", err);
      }
    };
    if (memoryId) loadFeedback();
  }, [memoryId, refreshKey]);

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

  return (
    <div className="w-full max-w-md mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white pb-1">
      <div className="px-6 py-4 flex justify-between items-center bg-zinc-800 border-b border-zinc-800">
        <h2 className="font-semibold flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" />
          Feedback
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
              disabled={isLoading || status === currentStatus}
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

      <ScrollArea className="max-h-[360px]">
        <div className="px-6 py-4">
          {feedbackHistory.length === 0 ? (
            <div className="text-center py-6">
              <Eye className="h-8 w-8 text-zinc-600 mx-auto mb-2" />
              <p className="text-zinc-500 text-sm">No feedback yet</p>
              <p className="text-zinc-600 text-xs mt-1">This memory has not been reviewed</p>
            </div>
          ) : (
            <div className="space-y-0">
              {feedbackHistory.map((record, index) => {
                const isLatest = index === feedbackHistory.length - 1;
                return (
                  <div key={record.id} className="relative">
                    <div className="flex items-start gap-3 pb-4">
                      <div className="relative z-10 flex-shrink-0 mt-0.5">
                        <div className={`w-7 h-7 rounded-full flex items-center justify-center ${
                          STATUS_CONFIG[record.status]?.bg || "bg-zinc-700"
                        }`}>
                          {STATUS_CONFIG[record.status]?.icon || <Eye className="h-3 w-3" />}
                        </div>
                      </div>
                      {index < feedbackHistory.length - 1 && (
                        <div className="absolute left-3.5 top-7 bottom-0 w-px bg-zinc-800" />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-sm font-medium ${STATUS_CONFIG[record.status]?.color || "text-zinc-300"}`}>
                            {STATUS_CONFIG[record.status]?.label || record.status}
                          </span>
                          {record.previous_status && (
                            <>
                              <ArrowRight className="h-3 w-3 text-zinc-600" />
                              <span className="text-xs text-zinc-500 line-through">
                                {STATUS_CONFIG[record.previous_status]?.label || record.previous_status}
                              </span>
                            </>
                          )}
                          {isLatest && (
                            <Badge variant="secondary" className="bg-primary/10 text-primary text-[10px] px-1.5 py-0">
                              Current
                            </Badge>
                          )}
                        </div>
                        {record.reason && (
                          <p className="text-zinc-400 text-xs mt-1 leading-relaxed">
                            {record.reason}
                          </p>
                        )}
                        <div className="flex items-center gap-3 mt-1.5">
                          <span className="text-zinc-600 text-[11px]">
                            {new Date(record.created_at * 1000).toLocaleDateString("en-US", {
                              month: "short",
                              day: "numeric",
                              hour: "numeric",
                              minute: "2-digit",
                            })}
                          </span>
                          {record.reviewer_id && (
                            <span className="text-zinc-600 text-[11px]">
                              by {record.reviewer_id.slice(0, 8)}
                            </span>
                          )}
                        </div>
                        {record.linked_history_id && (
                          <div className="flex items-center gap-1 mt-1.5">
                            <Link2 className="h-3 w-3 text-zinc-600" />
                            <History className="h-3 w-3 text-zinc-600" />
                            <span className="text-zinc-600 text-[11px]">
                              Linked to history event {record.linked_history_id.slice(0, 8)}...
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
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
            <label className="text-sm text-zinc-400 mb-2 block">
              Reason (optional)
            </label>
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
              disabled={isLoading}
              className="bg-primary hover:bg-primary/90 text-white"
            >
              {isLoading ? "Submitting..." : "Submit Feedback"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
