import {
  ActionGroup,
  Alert,
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  TextArea,
} from '@patternfly/react-core';
import { useState } from 'react';
import type { ReviewFeedbackItem } from '../api/types';

interface ReviewActionBarProps {
  onApprove: () => void;
  onRequestChanges: (feedback: ReviewFeedbackItem[], overallComment: string) => void;
  isApproving: boolean;
  isRequestingChanges: boolean;
  error?: Error | null;
  itemFeedback: Map<string, { itemType: ReviewFeedbackItem['itemType']; comment: string }>;
  reviewIteration: number;
}

export function ReviewActionBar({
  onApprove,
  onRequestChanges,
  isApproving,
  isRequestingChanges,
  error,
  itemFeedback,
  reviewIteration,
}: ReviewActionBarProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [overallComment, setOverallComment] = useState('');

  const feedbackCount = Array.from(itemFeedback.values()).filter(f => f.comment.trim()).length;
  const isBusy = isApproving || isRequestingChanges;

  function handleSubmitChanges() {
    const feedback: ReviewFeedbackItem[] = [];
    itemFeedback.forEach((value, itemId) => {
      if (value.comment.trim()) {
        feedback.push({
          itemId,
          itemType: value.itemType,
          comment: value.comment,
        });
      }
    });
    onRequestChanges(feedback, overallComment);
    setIsModalOpen(false);
    setOverallComment('');
  }

  return (
    <>
      {error && (
        <Alert variant="danger" title="Review action failed" isInline style={{ marginBottom: 16 }}>
          {error.message}
        </Alert>
      )}

      <ActionGroup style={{ marginTop: 24 }}>
        <Button
          variant="primary"
          onClick={onApprove}
          isDisabled={isBusy}
          isLoading={isApproving}
        >
          Approve &amp; Continue
        </Button>
        <Button
          variant="secondary"
          onClick={() => setIsModalOpen(true)}
          isDisabled={isBusy}
          isLoading={isRequestingChanges}
        >
          Request Changes{feedbackCount > 0 ? ` (${feedbackCount})` : ''}
        </Button>
        {reviewIteration > 1 && (
          <span style={{ color: 'var(--pf-t--global--text--color--subtle)', alignSelf: 'center' }}>
            Review iteration {reviewIteration}
          </span>
        )}
      </ActionGroup>

      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        variant="medium"
      >
        <ModalHeader title="Request Changes" />
        <ModalBody>
          {feedbackCount > 0 && (
            <Alert variant="info" title={`${feedbackCount} item-level feedback comment(s) will be included`} isInline style={{ marginBottom: 16 }} />
          )}
          <TextArea
            value={overallComment}
            onChange={(_e, value) => setOverallComment(value)}
            placeholder="Overall feedback or instructions for regeneration..."
            aria-label="Overall feedback"
            rows={4}
          />
        </ModalBody>
        <ModalFooter>
          <Button
            variant="primary"
            onClick={handleSubmitChanges}
            isDisabled={feedbackCount === 0 && !overallComment.trim()}
          >
            Submit Feedback
          </Button>
          <Button variant="link" onClick={() => setIsModalOpen(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </>
  );
}
