import { useMemo, useState } from "react";

export function usePendingChat() {
  const [pendingConvId, setPendingConvId] = useState<string | null>(null);
  const [pendingLabel, setPendingLabel] = useState<string | null>(null);
  const [pendingStartedAt, setPendingStartedAt] = useState<number | null>(null);

  const actions = useMemo(
    () => ({
      start(convId: string) {
        setPendingConvId(convId);
        setPendingStartedAt(Date.now());
      },
      clear() {
        setPendingConvId(null);
        setPendingLabel(null);
        setPendingStartedAt(null);
      },
      setLabel: setPendingLabel,
    }),
    [],
  );

  return {
    pendingConvId,
    pendingLabel,
    pendingStartedAt,
    ...actions,
  };
}
