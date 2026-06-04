import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const STORAGE_KEY = "wix_scanner_serial_devices";
const DEFAULT_ALLOWED_PATTERN = /^[\x20-\x7E]+$/;

export type WebSerialScannerOptions = {
  disabled?: boolean;
  baudRate?: number;
  maxPayloadLength?: number;
  allowedPattern?: RegExp;
  onScan: (payload: string) => void;
  onValidationError?: (reason: string) => void;
};

export type WebSerialScannerResult = {
  supported: boolean;
  connected: boolean;
  needsPermission: boolean;
  health: "responding" | "unresponsive" | "unknown";
  deviceLabel: string;
  rememberedDeviceCount: number;
  requestPermission: () => Promise<void>;
};

function portLabel(port: SerialPort): string {
  const info = port.getInfo();
  if (info.usbVendorId !== undefined && info.usbProductId !== undefined) {
    return `Serial (${info.usbVendorId.toString(16).padStart(4, "0")}:${info.usbProductId.toString(16).padStart(4, "0")})`;
  }
  return "Puerto Serie";
}

function persistPort(port: SerialPort): void {
  const info = port.getInfo();
  if (info.usbVendorId !== undefined) {
    const key = `${info.usbVendorId}:${info.usbProductId}`;
    const stored = readStoredPorts();
    if (!stored.includes(key)) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...stored, key]));
    }
  }
}

function readStoredPorts(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as string[]) : [];
  } catch {
    return [];
  }
}

export function useWebSerialScanner({
  disabled = false,
  baudRate = 9600,
  maxPayloadLength = 512,
  allowedPattern = DEFAULT_ALLOWED_PATTERN,
  onScan,
  onValidationError,
}: WebSerialScannerOptions): WebSerialScannerResult {
  const supported = !disabled && typeof navigator !== "undefined" && "serial" in navigator;

  const [connected, setConnected] = useState(false);
  const [needsPermission, setNeedsPermission] = useState(false);
  const [deviceLabel, setDeviceLabel] = useState("Sin dispositivo autorizado");
  const [rememberedDeviceCount, setRememberedDeviceCount] = useState(0);
  const [health, setHealth] = useState<"responding" | "unresponsive" | "unknown">("unknown");

  // Use refs for callbacks so the read loop never has stale closures and
  // startReading stays stable even when the parent re-renders with new callbacks.
  const onScanRef = useRef(onScan);
  const onValidationErrorRef = useRef(onValidationError);
  const allowedPatternRef = useRef(allowedPattern);
  const maxPayloadLengthRef = useRef(maxPayloadLength);

  useEffect(() => { onScanRef.current = onScan; }, [onScan]);
  useEffect(() => { onValidationErrorRef.current = onValidationError; }, [onValidationError]);
  useEffect(() => { allowedPatternRef.current = allowedPattern; }, [allowedPattern]);
  useEffect(() => { maxPayloadLengthRef.current = maxPayloadLength; }, [maxPayloadLength]);

  const portRef = useRef<SerialPort | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<string> | null>(null);
  const readingRef = useRef(false);

  const flushBuffer = useCallback((raw: string) => {
    const payload = raw.trim();
    if (!payload) return;
    if (payload.length > maxPayloadLengthRef.current) {
      onValidationErrorRef.current?.("max_length");
      return;
    }
    if (!allowedPatternRef.current.test(payload)) {
      onValidationErrorRef.current?.("invalid_charset");
      return;
    }
    onScanRef.current(payload);
  }, []);

  const startReading = useCallback(async (port: SerialPort) => {
    if (readingRef.current) return;
    readingRef.current = true;

    try {
      if (!port.readable) {
        await port.open({ baudRate });
      }
      portRef.current = port;
      persistPort(port);
      setDeviceLabel(portLabel(port));
      setRememberedDeviceCount(readStoredPorts().length);
      setConnected(true);
      setHealth("responding");
      setNeedsPermission(false);

      const reader = port.readable!.pipeThrough(new TextDecoderStream()).getReader();
      readerRef.current = reader;

      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const char of value) {
          if (char === "\r" || char === "\n") {
            if (buffer) {
              flushBuffer(buffer);
              buffer = "";
            }
          } else if (buffer.length >= maxPayloadLengthRef.current) {
            buffer = "";
            onValidationErrorRef.current?.("max_length");
          } else {
            buffer += char;
          }
        }
      }
    } catch {
      // Port closed or cancelled
    } finally {
      readingRef.current = false;
      readerRef.current = null;
      if (portRef.current === port) {
        portRef.current = null;
        try { await port.close(); } catch { /* already closed */ }
        setConnected(false);
        setHealth("unknown");
      }
    }
  }, [baudRate, flushBuffer]);

  useEffect(() => {
    if (!supported) return;

    void (async () => {
      const ports = await navigator.serial.getPorts();
      setRememberedDeviceCount(readStoredPorts().length);

      if (ports.length === 0) {
        setNeedsPermission(true);
        return;
      }

      // Connect to the first granted port. If multiple same-model devices are
      // plugged in simultaneously (same VID:PID), the first one wins.
      await startReading(ports[0]);
    })();

    const onSerialConnect = async (event: SerialConnectionEvent) => {
      if (!portRef.current) {
        await startReading(event.port);
      }
    };

    const onSerialDisconnect = (event: SerialConnectionEvent) => {
      if (portRef.current === event.port) {
        readerRef.current?.cancel();
      }
    };

    navigator.serial.addEventListener("connect", onSerialConnect);
    navigator.serial.addEventListener("disconnect", onSerialDisconnect);

    return () => {
      navigator.serial.removeEventListener("connect", onSerialConnect);
      navigator.serial.removeEventListener("disconnect", onSerialDisconnect);
      readerRef.current?.cancel();
    };
  }, [supported, startReading]);

  const requestPermission = useCallback(async () => {
    if (!supported) return;
    const port = await navigator.serial.requestPort({});
    await startReading(port);
  }, [supported, startReading]);

  return useMemo(
    () => ({
      supported,
      connected,
      needsPermission,
      health,
      deviceLabel,
      rememberedDeviceCount,
      requestPermission,
    }),
    [supported, connected, needsPermission, health, deviceLabel, rememberedDeviceCount, requestPermission],
  );
}
