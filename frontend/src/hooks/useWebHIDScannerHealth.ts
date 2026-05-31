import { useCallback, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "wix_scanner_hid_devices";

type WebHIDStatus = {
  supported: boolean;
  connected: boolean;
  health: "responding" | "unresponsive" | "unknown";
  deviceLabel: string;
  rememberedDeviceCount: number;
  requestPermission: () => Promise<void>;
};

function formatDevice(device: HIDDevice): string {
  const name = device.productName ?? "Scanner HID";
  return `${name} (${device.vendorId}:${device.productId})`;
}

function persistRememberedDevices(devices: HIDDevice[]) {
  const values = devices.map((d) => `${d.vendorId}:${d.productId}`);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(values));
}

function readRememberedDevices(): string[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      return [];
    }
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function useWebHIDScannerHealth(): WebHIDStatus {
  const supported = typeof navigator !== "undefined" && "hid" in navigator;
  const [device, setDevice] = useState<HIDDevice | null>(null);
  const [health, setHealth] = useState<"responding" | "unresponsive" | "unknown">("unknown");
  const [rememberedDeviceCount, setRememberedDeviceCount] = useState(0);

  const refreshDevices = useCallback(async () => {
    if (!supported) {
      return;
    }

    const devices = await navigator.hid.getDevices();
    setDevice(devices[0] ?? null);
    setRememberedDeviceCount(readRememberedDevices().length);
    if (devices.length > 0) {
      persistRememberedDevices(devices);
    }
  }, [supported]);

  const requestPermission = useCallback(async () => {
    if (!supported) {
      return;
    }

    const requested = await navigator.hid.requestDevice({ filters: [] });
    if (requested.length > 0) {
      persistRememberedDevices(requested);
      await refreshDevices();
    }
  }, [refreshDevices, supported]);

  useEffect(() => {
    if (!supported) {
      return;
    }

    void refreshDevices();

    const onConnect = (event: HIDConnectionEvent) => {
      setDevice(event.device);
      void refreshDevices();
    };
    const onDisconnect = () => {
      setDevice(null);
      setHealth("unknown");
      void refreshDevices();
    };

    navigator.hid.addEventListener("connect", onConnect);
    navigator.hid.addEventListener("disconnect", onDisconnect);

    return () => {
      navigator.hid.removeEventListener("connect", onConnect);
      navigator.hid.removeEventListener("disconnect", onDisconnect);
    };
  }, [refreshDevices, supported]);

  useEffect(() => {
    if (!supported) {
      return;
    }

    const checkHealth = async () => {
      if (!device) {
        setHealth("unknown");
        return;
      }

      try {
        if (!device.opened) {
          await device.open();
        }

        const maybeWritable = device as unknown as {
          collections?: Array<{ outputReports?: Array<{ reportId: number }> }>;
          sendReport?: (reportId: number, data: BufferSource) => Promise<void>;
        };
        const reportId = maybeWritable.collections?.[0]?.outputReports?.[0]?.reportId;
        if (typeof reportId === "number" && maybeWritable.sendReport) {
          await maybeWritable.sendReport(reportId, new Uint8Array([0]));
        }

        setHealth("responding");
      } catch {
        setHealth("unresponsive");
      }
    };

    void checkHealth();
    const interval = window.setInterval(() => {
      void checkHealth();
    }, 10_000);

    return () => {
      window.clearInterval(interval);
    };
  }, [device, supported]);

  return useMemo(
    () => ({
      supported,
      connected: Boolean(device),
      health,
      deviceLabel: device ? formatDevice(device) : "Sin dispositivo autorizado",
      rememberedDeviceCount,
      requestPermission,
    }),
    [device, health, rememberedDeviceCount, requestPermission, supported],
  );
}
