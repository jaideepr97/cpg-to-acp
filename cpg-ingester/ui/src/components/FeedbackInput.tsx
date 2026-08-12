import {
  Button,
  TextArea,
} from '@patternfly/react-core';
import { useState } from 'react';

interface FeedbackInputProps {
  itemId: string;
  onFeedbackChange: (itemId: string, comment: string) => void;
  existingComment?: string;
}

export function FeedbackInput({ itemId, onFeedbackChange, existingComment }: FeedbackInputProps) {
  const [isOpen, setIsOpen] = useState(!!existingComment);
  const [comment, setComment] = useState(existingComment ?? '');

  if (!isOpen) {
    return (
      <Button
        variant="link"
        isInline
        onClick={() => setIsOpen(true)}
      >
        Add Feedback
      </Button>
    );
  }

  return (
    <div style={{ marginTop: 8 }}>
      <TextArea
        value={comment}
        onChange={(_e, value) => {
          setComment(value);
          onFeedbackChange(itemId, value);
        }}
        placeholder="Describe what should change..."
        aria-label={`Feedback for ${itemId}`}
        rows={2}
        autoFocus
      />
      {!existingComment && (
        <Button
          variant="link"
          isInline
          onClick={() => {
            setIsOpen(false);
            setComment('');
            onFeedbackChange(itemId, '');
          }}
          style={{ marginTop: 4 }}
        >
          Remove
        </Button>
      )}
    </div>
  );
}
