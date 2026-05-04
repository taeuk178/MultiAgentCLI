import { useCallback, useEffect, useMemo, useState } from "react";
import { providerStatuses } from "../lib/ipc";
import {
  makeDefaultProviderRuntime,
  providerHealth,
} from "../lib/conversations";
import {
  PROVIDER_IDS,
  type ProviderId,
  type ProviderRuntimeStatus,
} from "../lib/types";

export function useProviderRuntime() {
  const [runtime, setRuntime] = useState<Record<ProviderId, ProviderRuntimeStatus>>(
    makeDefaultProviderRuntime(),
  );

  const applyRuntime = useCallback((statuses: ProviderRuntimeStatus[]) => {
    setRuntime((prev) => {
      const next = { ...prev };
      for (const status of statuses) {
        next[status.providerId] = status;
      }
      return next;
    });
  }, []);

  const refresh = useCallback(async () => {
    const statuses = await providerStatuses();
    applyRuntime(statuses);
  }, [applyRuntime]);

  useEffect(() => {
    let cancelled = false;

    providerStatuses()
      .then((statuses) => {
        if (!cancelled) {
          applyRuntime(statuses);
        }
      })
      .catch(() => {
        if (cancelled) return;
        setRuntime((prev) => {
          const next = { ...prev };
          for (const id of PROVIDER_IDS) {
            next[id] = { ...next[id], health: "error" };
          }
          return next;
        });
      });

    return () => {
      cancelled = true;
    };
  }, [applyRuntime]);

  const health = useMemo(() => providerHealth(runtime), [runtime]);

  return { runtime, health, refresh };
}
