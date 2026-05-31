import { useCallback, useEffect, useRef, useState } from "react";

export type KioskSession = {
  bootstrapSessionId: string;
  activeEventId: string;
  activeStationId: string;
  /** Unix timestamp (seconds) when the session expires. */
  expiresAt: number;
};

const STORAGE_KEY = "kiosk_session";

function loadSession(): KioskSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as KioskSession;
    if (session.expiresAt < Math.floor(Date.now() / 1000)) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

function saveSession(session: KioskSession): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

function clearStoredSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export type UseKioskSessionReturn = {
  session: KioskSession | null;
  enrolled: boolean;
  enroll: (session: KioskSession) => void;
  clearSession: () => void;
};

/**
 * Manages kiosk station enrollment state.
 *
 * - Session is persisted in localStorage so it survives page reloads.
 * - An expiry timer automatically clears an expired session.
 * - `enrolled` is true only while a non-expired session is in memory.
 */
export function useKioskSession(): UseKioskSessionReturn {
  const [session, setSession] = useState<KioskSession | null>(() => loadSession());
  const expiryTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);

  // Set up (or reset) the expiry timer whenever the session changes.
  useEffect(() => {
    if (expiryTimerRef.current !== null) {
      window.clearTimeout(expiryTimerRef.current);
      expiryTimerRef.current = null;
    }

    if (!session) return;

    const msUntilExpiry = session.expiresAt * 1000 - Date.now();
    if (msUntilExpiry <= 0) {
      clearStoredSession();
      setSession(null);
      return;
    }

    expiryTimerRef.current = window.setTimeout(() => {
      clearStoredSession();
      setSession(null);
    }, msUntilExpiry);

    return () => {
      if (expiryTimerRef.current !== null) {
        window.clearTimeout(expiryTimerRef.current);
      }
    };
  }, [session]);

  const enroll = useCallback((newSession: KioskSession) => {
    saveSession(newSession);
    setSession(newSession);
  }, []);

  const clearSession = useCallback(() => {
    clearStoredSession();
    setSession(null);
  }, []);

  return {
    session,
    enrolled: session !== null,
    enroll,
    clearSession,
  };
}
