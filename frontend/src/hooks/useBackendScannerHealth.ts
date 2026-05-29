import { useEffect, useState } from "react";

import { fetchScannerHealth, type ScannerHealthResponse } from "@/services/scannerApi";

export function useBackendScannerHealth(activeEventId?: string) {
  const [data, setData] = useState<ScannerHealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    const poll = async () => {
      try {
        const response = await fetchScannerHealth(activeEventId);
        if (!mounted) {
          return;
        }
        setData(response);
        setError(null);
      } catch (err) {
        if (!mounted) {
          return;
        }
        setError(err instanceof Error ? err.message : "health_failed");
      }
    };

    void poll();
    const interval = window.setInterval(() => {
      void poll();
    }, 5000);

    return () => {
      mounted = false;
      window.clearInterval(interval);
    };
  }, [activeEventId]);

  return {
    data,
    error,
  };
}
