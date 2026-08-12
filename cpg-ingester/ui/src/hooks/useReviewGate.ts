import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { ReviewAction, ReviewFeedbackItem, RunDetail } from '../api/types';

export function useReviewGate(run: RunDetail) {
  const queryClient = useQueryClient();
  const gate = run.awaitingReview;

  const approveMutation = useMutation({
    mutationFn: () => {
      if (!gate) throw new Error('No review gate active');
      const action: ReviewAction = { action: 'approve' };
      return api.submitReview(run.id, gate, action);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', run.id] });
    },
  });

  const requestChangesMutation = useMutation({
    mutationFn: (params: { feedback: ReviewFeedbackItem[]; overallComment?: string }) => {
      if (!gate) throw new Error('No review gate active');
      const action: ReviewAction = {
        action: 'request_changes',
        feedback: params.feedback,
        overallComment: params.overallComment,
      };
      return api.submitReview(run.id, gate, action);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', run.id] });
    },
  });

  return {
    gate,
    reviewIteration: run.reviewIteration ?? 1,
    previousFeedback: run.previousFeedback,
    isReviewActive: !!gate,
    approveMutation,
    requestChangesMutation,
  };
}
