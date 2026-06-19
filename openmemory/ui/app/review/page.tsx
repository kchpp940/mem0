"use client";

import { useEffect, useState } from "react";
import { useFeedbackApi, FeedbackQueueItem, FeedbackStatusType } from "@/hooks/useFeedbackApi";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  ClipboardCheck,
  ArrowRight,
  Eye,
  RefreshCw,
} from "lucide-react";

const STATUS_CONFIG: Record<FeedbackStatusType, { label: string; icon: React.ReactNode; color: string; bg: string }> = {
  needs_review: {
    label: "Needs Review",
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
    color: "text-amber-400",
    bg: "bg-amber-400/10 border-amber-400/30",
  },
  incorrect: {
    label: "Incorrect",
    icon: <XCircle className="h-3.5 w-3.5" />,
    color: "text-red-400",
    bg: "bg-red-400/10 border-red-400/30",
  },
  outdated: {
    label: "Outdated",
    icon: <Clock className="h-3.5 w-3.5" />,
    color: "text-orange-400",
    bg: "bg-orange-400/10 border-orange-400/30",
  },
  confirmed: {
    label: "Confirmed",
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    color: "text-emerald-400",
    bg: "bg-emerald-400/10 border-emerald-400/30",
  },
  unreviewed: {
    label: "Unreviewed",
    icon: <Eye className="h-3.5 w-3.5" />,
    color: "text-zinc-400",
    bg: "bg-zinc-400/10 border-zinc-400/30",
  },
};

type TabStatus = "needs_review" | "incorrect" | "outdated";

export default function ReviewQueuePage() {
  const router = useRouter();
  const { fetchFeedbackQueue, submitFeedback, isLoading } = useFeedbackApi();
  const [items, setItems] = useState<FeedbackQueueItem[]>([]);
  const [activeTab, setActiveTab] = useState<TabStatus>("needs_review");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const loadQueue = async () => {
      try {
        const data = await fetchFeedbackQueue(activeTab);
        setItems(data);
      } catch (err) {
        console.error("Failed to load review queue:", err);
      }
    };
    loadQueue();
  }, [activeTab, refreshKey]);

  const handleQuickConfirm = async (memoryId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await submitFeedback(memoryId, "confirmed", "Quick confirmed from review queue");
      setItems((prev) => prev.filter((item) => item.memory_id !== memoryId));
    } catch (err) {
      console.error("Failed to confirm memory:", err);
    }
  };

  const handleRefresh = () => setRefreshKey((k) => k + 1);

  const tabs: { key: TabStatus; label: string }[] = [
    { key: "needs_review", label: "Needs Review" },
    { key: "incorrect", label: "Incorrect" },
    { key: "outdated", label: "Outdated" },
  ];

  return (
    <div className="container mx-auto py-6 px-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <ClipboardCheck className="h-6 w-6 text-primary" />
            Review Queue
          </h1>
          <p className="text-zinc-400 text-sm mt-1">
            Review and manage memory feedback statuses
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={isLoading}
          className="border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800 text-zinc-300"
        >
          <RefreshCw className={`h-3.5 w-3.5 mr-1 ${isLoading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <div className="flex gap-2 mb-6">
        {tabs.map((tab) => (
          <Button
            key={tab.key}
            variant="outline"
            size="sm"
            onClick={() => setActiveTab(tab.key)}
            className={`${
              activeTab === tab.key
                ? "bg-zinc-800 text-white border-zinc-600"
                : "text-zinc-400 border-zinc-800 hover:bg-zinc-900"
            }`}
          >
            {STATUS_CONFIG[tab.key].icon}
            <span className="ml-1.5 font-semibold">{tab.label}</span>
            {activeTab === tab.key && items.length > 0 && (
              <Badge variant="secondary" className="ml-2 bg-zinc-700 text-zinc-200 text-xs px-1.5">
                {items.length}
              </Badge>
            )}
          </Button>
        ))}
      </div>

      {isLoading && items.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <p className="text-zinc-500">Loading review queue...</p>
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <CheckCircle2 className="h-12 w-12 text-emerald-500/40" />
          <p className="text-zinc-400 text-lg font-medium">All caught up!</p>
          <p className="text-zinc-500 text-sm">
            No memories with &ldquo;{STATUS_CONFIG[activeTab].label}&rdquo; status
          </p>
        </div>
      ) : (
        <ScrollArea className="h-[calc(100vh-260px)]">
          <div className="space-y-3">
            {items.map((item) => (
              <Card
                key={item.memory_id}
                className="bg-zinc-900 border-zinc-800 hover:border-zinc-700 transition-colors cursor-pointer"
                onClick={() => router.push(`/memory/${item.memory_id}`)}
              >
                <div className="p-4 flex items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge
                        variant="outline"
                        className={`${STATUS_CONFIG[activeTab].bg} ${STATUS_CONFIG[activeTab].color} border text-xs`}
                      >
                        {STATUS_CONFIG[activeTab].icon}
                        <span className="ml-1">{STATUS_CONFIG[activeTab].label}</span>
                      </Badge>
                      {item.app_name && (
                        <Badge variant="outline" className="bg-zinc-800 text-zinc-400 border-zinc-700 text-xs">
                          {item.app_name}
                        </Badge>
                      )}
                    </div>
                    <p className="text-zinc-200 text-sm leading-relaxed line-clamp-2">
                      {item.content_preview}
                    </p>
                    <p className="text-zinc-500 text-xs mt-2">
                      {new Date(item.created_at * 1000).toLocaleDateString("en-US", {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {activeTab === "needs_review" && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => handleQuickConfirm(item.memory_id, e)}
                        disabled={isLoading}
                        className="border-emerald-600/50 text-emerald-400 hover:bg-emerald-400/10 hover:text-emerald-300 text-xs"
                      >
                        <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
                        Confirm
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-zinc-400 hover:text-white text-xs"
                    >
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
