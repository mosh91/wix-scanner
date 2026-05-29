import { useEffect, useRef } from "react";

type HIDScannerOptions = {
  terminatorKey?: string;
  debounceMs?: number;
  maxPayloadLength?: number;
  allowedPattern?: RegExp;
  onScan: (payload: string) => void;
  onValidationError?: (reason: string) => void;
};

const DEFAULT_ALLOWED_PATTERN = /^[\x20-\x7E]+$/;

export function useHIDScanner({
  terminatorKey = "Enter",
  debounceMs = 50,
  maxPayloadLength = 512,
  allowedPattern = DEFAULT_ALLOWED_PATTERN,
  onScan,
  onValidationError,
}: HIDScannerOptions): void {
  const bufferRef = useRef("");
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    const flush = () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }

      const payload = bufferRef.current.trim();
      bufferRef.current = "";

      if (!payload) {
        return;
      }
      if (payload.length > maxPayloadLength) {
        onValidationError?.("max_length");
        return;
      }
      if (!allowedPattern.test(payload)) {
        onValidationError?.("invalid_charset");
        return;
      }

      onScan(payload);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      if (event.key === terminatorKey) {
        if (debounceRef.current) {
          window.clearTimeout(debounceRef.current);
        }
        debounceRef.current = window.setTimeout(flush, debounceMs);
        return;
      }

      if (event.key.length !== 1) {
        return;
      }

      if (bufferRef.current.length >= maxPayloadLength) {
        bufferRef.current = "";
        onValidationError?.("max_length");
        return;
      }

      bufferRef.current += event.key;
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, [allowedPattern, debounceMs, maxPayloadLength, onScan, onValidationError, terminatorKey]);
}
