import { useState, useCallback } from 'react';
import axios from 'axios';
import { useSelector } from 'react-redux';
import { RootState } from '@/store/store';

export type FeedbackStatusType = 'unreviewed' | 'confirmed' | 'incorrect' | 'outdated' | 'needs_review';

export interface FeedbackRecord {
  id: string;
  memory_id: string;
  status: FeedbackStatusType;
  reason: string | null;
  reviewer_id: string | null;
  previous_status: FeedbackStatusType | null;
  linked_history_id: string | null;
  created_at: number;
}

export interface FeedbackQueueItem {
  memory_id: string;
  content_preview: string;
  app_id: string | null;
  app_name: string | null;
  created_at: number;
  reviewer_id: string | null;
}

interface FeedbackListResponse {
  memory_id: string;
  feedback: FeedbackRecord[];
}

interface FeedbackQueueResponse {
  status: string;
  total: number;
  items: FeedbackQueueItem[];
}

interface SubmitFeedbackResponse {
  message: string;
  feedback: FeedbackRecord;
}

interface UseFeedbackApiReturn {
  submitFeedback: (memoryId: string, status: FeedbackStatusType, reason?: string, reviewerId?: string) => Promise<SubmitFeedbackResponse>;
  fetchFeedbackHistory: (memoryId: string) => Promise<FeedbackRecord[]>;
  fetchFeedbackQueue: (status: FeedbackStatusType, appId?: string) => Promise<FeedbackQueueItem[]>;
  isLoading: boolean;
  error: string | null;
}

export const useFeedbackApi = (): UseFeedbackApiReturn => {
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const user_id = useSelector((state: RootState) => state.profile.userId);
  const URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8765";

  const submitFeedback = useCallback(async (
    memoryId: string,
    status: FeedbackStatusType,
    reason?: string,
    reviewerId?: string
  ): Promise<SubmitFeedbackResponse> => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.post<SubmitFeedbackResponse>(
        `${URL}/api/v1/memories/${memoryId}/feedback`,
        {
          user_id,
          status,
          reason: reason || null,
          reviewer_id: reviewerId || null,
        }
      );
      setIsLoading(false);
      return response.data;
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || 'Failed to submit feedback';
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  }, [user_id]);

  const fetchFeedbackHistory = useCallback(async (memoryId: string): Promise<FeedbackRecord[]> => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.get<FeedbackListResponse>(
        `${URL}/api/v1/memories/${memoryId}/feedback?user_id=${user_id}`
      );
      setIsLoading(false);
      return response.data.feedback;
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || 'Failed to fetch feedback history';
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  }, [user_id]);

  const fetchFeedbackQueue = useCallback(async (
    status: FeedbackStatusType,
    appId?: string
  ): Promise<FeedbackQueueItem[]> => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await axios.post<FeedbackQueueResponse>(
        `${URL}/api/v1/memories/feedback/status`,
        {
          user_id,
          status,
          app_id: appId || undefined,
        }
      );
      setIsLoading(false);
      return response.data.items;
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message || 'Failed to fetch feedback queue';
      setError(errorMessage);
      setIsLoading(false);
      throw new Error(errorMessage);
    }
  }, [user_id]);

  return {
    submitFeedback,
    fetchFeedbackHistory,
    fetchFeedbackQueue,
    isLoading,
    error,
  };
};
