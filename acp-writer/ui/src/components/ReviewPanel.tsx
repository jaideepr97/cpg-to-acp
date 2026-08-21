import { useState } from "react";
import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Flex,
  FlexItem,
  Stack,
  StackItem,
  TextArea,
  TextInput,
} from "@patternfly/react-core";
import type { CarePlanView, ReviewAction } from "@app/api/models";
import { GoalCard } from "./GoalCard";
import { ActivityCard } from "./ActivityCard";
import { ConflictAlert } from "./ConflictAlert";

interface ReviewPanelProps {
  carePlan: CarePlanView;
  reviewIteration?: number;
  previousFeedback?: ReviewAction | null;
  onSubmit: (action: ReviewAction) => Promise<void>;
}

export function ReviewPanel({
  carePlan,
  reviewIteration,
  previousFeedback,
  onSubmit,
}: ReviewPanelProps) {
  const [mode, setMode] = useState<"idle" | "changes">("idle");
  const [clinician, setClinician] = useState("");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const goals = carePlan.goals ?? [];
  const activities = carePlan.activities ?? [];
  const conflicts = carePlan.conflicts ?? [];

  const submit = async (action: ReviewAction) => {
    setSubmitting(true);
    try {
      await onSubmit(action);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardTitle>
        Care-plan review{typeof reviewIteration === "number" ? ` — round ${reviewIteration + 1}` : ""}
      </CardTitle>
      <CardBody>
        <Stack hasGutter>
          {previousFeedback?.comment && (
            <StackItem>
              <em>Previously requested:</em> {previousFeedback.comment}
            </StackItem>
          )}
          {conflicts.map((c) => (
            <StackItem key={c.id}><ConflictAlert conflict={c} /></StackItem>
          ))}
          <StackItem>
            <strong>Goals ({goals.length})</strong>
            <Stack hasGutter>
              {goals.map((g) => <StackItem key={g.id}><GoalCard goal={g} /></StackItem>)}
            </Stack>
          </StackItem>
          <StackItem>
            <strong>Activities ({activities.length})</strong>
            <Stack hasGutter>
              {activities.map((a) => <StackItem key={a.id}><ActivityCard activity={a} /></StackItem>)}
            </Stack>
          </StackItem>

          <StackItem>
            <TextInput
              aria-label="Clinician name"
              placeholder="Clinician name"
              value={clinician}
              onChange={(_e, v) => setClinician(v)}
            />
          </StackItem>

          {mode === "changes" && (
            <StackItem>
              <TextArea
                aria-label="Overall comment"
                placeholder="What should change?"
                value={comment}
                onChange={(_e, v) => setComment(v)}
              />
            </StackItem>
          )}

          <StackItem>
            <Flex gap={{ default: "gapSm" }}>
              {mode === "idle" ? (
                <>
                  <FlexItem>
                    <Button
                      variant="primary"
                      isLoading={submitting}
                      isDisabled={submitting}
                      onClick={() =>
                        submit({ decision: "approve", clinician: clinician || undefined })
                      }
                    >
                      Approve
                    </Button>
                  </FlexItem>
                  <FlexItem>
                    <Button variant="secondary" onClick={() => setMode("changes")}>
                      Request changes
                    </Button>
                  </FlexItem>
                </>
              ) : (
                <>
                  <FlexItem>
                    <Button
                      variant="primary"
                      isLoading={submitting}
                      isDisabled={submitting || !comment.trim()}
                      onClick={() =>
                        submit({
                          decision: "request_changes",
                          clinician: clinician || undefined,
                          comment: comment.trim(),
                        })
                      }
                    >
                      Submit changes
                    </Button>
                  </FlexItem>
                  <FlexItem>
                    <Button variant="link" onClick={() => setMode("idle")}>
                      Cancel
                    </Button>
                  </FlexItem>
                </>
              )}
            </Flex>
          </StackItem>
        </Stack>
      </CardBody>
    </Card>
  );
}
