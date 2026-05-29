import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, KeyRound, LoaderCircle, LogOut, QrCode, Usb } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { useBackendScannerHealth } from "@/hooks/useBackendScannerHealth";
import { useHIDScanner } from "@/hooks/useHIDScanner";
import { useKioskSession } from "@/hooks/useKioskSession";
import { useWebHIDScannerHealth } from "@/hooks/useWebHIDScannerHealth";
import {
  clearBootstrapSession,
  isBootstrapQR,
  submitScan,
  validateBootstrapQR,
  type ScanResponse,
} from "@/services/scannerApi";

type KioskMode =
  | "bootstrap-idle"
  | "bootstrap-success"
  | "bootstrap-error"
  | "idle"
  | "success"
  | "error";

type ScanHistoryItem = {
  id: string;
  ticket: string;
  status: ScanResponse["status"];
  reason: string | null;
  errorCode: string;
  wixStatus: string;
  timestamp: number;
  responseTimeMs: number;
};

const KIOSK_RESET_MS = {
  success: 2500,
  error: 3000,
};

function getStatusBadgeVariant(status: ScanResponse["status"]): "default" | "secondary" | "outline" {
  if (status === "CHECKED_IN") {
    return "default";
  }
  if (status === "ALREADY_CHECKED_IN") {
    return "secondary";
  }
  return "outline";
}

function formatClock(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function OperatorPage() {
  const { t } = useTranslation();
  const { session, enrolled, enroll, clearSession } = useKioskSession();
  const [sessionId] = useState(() => `session-${crypto.randomUUID()}`);
  const [operatorId] = useState("operator-local");

  // Initial mode depends on enrollment state (evaluated synchronously on first render).
  const [mode, setMode] = useState<KioskMode>(enrolled ? "idle" : "bootstrap-idle");
  const [currentTicket, setCurrentTicket] = useState<string | null>(null);
  const [currentReason, setCurrentReason] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isWindowFocused, setIsWindowFocused] = useState(document.hasFocus());
  const [scanHistory, setScanHistory] = useState<ScanHistoryItem[]>([]);
  const [selectedHistoryItem, setSelectedHistoryItem] = useState<ScanHistoryItem | null>(null);
  const isFirstMountRef = useRef(true);

  const webhid = useWebHIDScannerHealth();
  const backendHealth = useBackendScannerHealth();

  // When the session expires, return to bootstrap-idle.
  useEffect(() => {
    if (!enrolled) {
      setMode("bootstrap-idle");
      if (!isFirstMountRef.current) {
        toast.warning(t("bootstrap.sessionExpired"));
      }
    }
    isFirstMountRef.current = false;
  }, [enrolled, t]);

  const metrics = useMemo(() => {
    const last20 = scanHistory.slice(0, 20).map((item) => item.responseTimeMs);
    const min = last20.length > 0 ? Math.min(...last20) : 0;
    const max = last20.length > 0 ? Math.max(...last20) : 0;
    const avg = last20.length > 0 ? Math.round(last20.reduce((acc, value) => acc + value, 0) / last20.length) : 0;
    const successCount = scanHistory.filter((item) => item.status === "CHECKED_IN").length;
    const successRate = scanHistory.length > 0 ? Math.round((successCount / scanHistory.length) * 100) : 100;

    return {
      history: last20,
      min,
      max,
      avg,
      successRate,
    };
  }, [scanHistory]);

  useEffect(() => {
    const onFocus = () => setIsWindowFocused(true);
    const onBlur = () => {
      setIsWindowFocused(false);
      setMode("idle");
      toast.warning(t("operator.focusLost"));
    };

    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);

    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
    };
  }, [t]);

  useEffect(() => {
    if (!webhid.supported) {
      toast.warning(t("operator.webhidUnavailable"));
      return;
    }
    if (!webhid.connected) {
      toast.warning(t("operator.scannerDisconnected"));
    }
  }, [t, webhid.connected, webhid.supported]);

  useEffect(() => {
    if (!backendHealth.data) {
      return;
    }
    if (backendHealth.data.backend_status === "red") {
      toast.error(t("operator.backendDegraded"));
    }
  }, [backendHealth.data, t]);

  const processBootstrapQR = async (payload: string) => {
    const overlayTimer = window.setTimeout(() => setIsProcessing(true), 300);
    try {
      const result = await validateBootstrapQR({
        payload,
        current_event_id: session?.activeEventId,
      });
      enroll({
        bootstrapSessionId: result.bootstrap_session_id,
        activeEventId: result.event_id,
        activeStationId: result.station_id,
        expiresAt: result.expires_at,
      });
      setCurrentReason(null);
      setMode("bootstrap-success");
      toast.success(
        t("bootstrap.enrolledToast", { event: result.event_id, station: result.station_id }),
      );
      window.setTimeout(() => setMode("idle"), KIOSK_RESET_MS.success);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("bootstrap.unknownError");
      setCurrentReason(msg);
      setMode("bootstrap-error");
      window.setTimeout(
        () => setMode(enrolled ? "idle" : "bootstrap-idle"),
        KIOSK_RESET_MS.error,
      );
    } finally {
      window.clearTimeout(overlayTimer);
      setIsProcessing(false);
    }
  };

  const processTicketScan = async (payload: string) => {
    const overlayTimer = window.setTimeout(() => {
      setIsProcessing(true);
    }, 300);

    try {
      const result = await submitScan(payload, {
        source: "hid",
        sessionId,
        operatorId,
        scannerStatus: webhid.connected ? "connected" : "disconnected",
        activeEventId: session?.activeEventId,
        activeStationId: session?.activeStationId,
      });

      const item: ScanHistoryItem = {
        id: result.idempotency_key,
        ticket: result.ticket_number,
        status: result.status,
        reason: result.reason,
        errorCode: result.error_code,
        wixStatus: result.wix_status,
        timestamp: Date.now(),
        responseTimeMs: result.response_time_ms,
      };

      setScanHistory((prev) => [item, ...prev].slice(0, 25));
      setCurrentTicket(result.ticket_number);
      setCurrentReason(result.reason);

      if (result.status === "CHECKED_IN") {
        setMode("success");
        window.setTimeout(() => setMode("idle"), KIOSK_RESET_MS.success);
      } else {
        setMode("error");
        window.setTimeout(() => setMode("idle"), KIOSK_RESET_MS.error);
      }
    } catch {
      setMode("error");
      setCurrentReason(t("operator.offlineQueued"));
      toast.warning(t("operator.offlineQueued"));
      window.setTimeout(() => setMode("idle"), KIOSK_RESET_MS.error);
    } finally {
      window.clearTimeout(overlayTimer);
      setIsProcessing(false);
    }
  };

  const processScan = (payload: string) => {
    if (isBootstrapQR(payload)) {
      void processBootstrapQR(payload);
      return;
    }
    if (!enrolled) {
      setCurrentReason(t("bootstrap.notEnrolledError"));
      setMode("bootstrap-error");
      toast.error(t("bootstrap.notEnrolledError"));
      window.setTimeout(() => setMode("bootstrap-idle"), KIOSK_RESET_MS.error);
      return;
    }
    void processTicketScan(payload);
  };

  useHIDScanner({
    onScan: (payload) => {
      processScan(payload);
    },
    onValidationError: (reason) => {
      if (reason === "max_length") {
        toast.error(t("operator.validation.maxLength"));
      } else {
        toast.error(t("operator.validation.invalidCharset"));
      }
    },
    debounceMs: 50,
    maxPayloadLength: 512,
  });

  const handleClearSession = async () => {
    if (session?.bootstrapSessionId) {
      try {
        await clearBootstrapSession(session.bootstrapSessionId);
      } catch {
        // Clear locally even if the backend call fails
      }
    }
    clearSession();
    setMode("bootstrap-idle");
    setCurrentTicket(null);
    setCurrentReason(null);
    setScanHistory([]);
    toast.info(t("bootstrap.sessionCleared"));
  };

  const kioskPalette =
    mode === "bootstrap-idle" || mode === "idle"
      ? "bg-slate-900"
      : mode === "bootstrap-success" || mode === "success"
        ? "bg-emerald-500"
        : "bg-rose-600";

  return (
    <section className={`min-h-screen w-full ${kioskPalette} text-white`}>
      <div className="grid min-h-screen gap-4 p-4 lg:grid-cols-[2fr_1fr]">
        <Card className="relative border-white/20 bg-transparent text-white shadow-none">
          <CardContent className="flex min-h-[62vh] flex-col items-center justify-center gap-8 px-6 py-10 text-center">
            {/* ── Bootstrap states ── */}
            {mode === "bootstrap-idle" && (
              <>
                <div className="relative">
                  <div className="absolute inset-0 animate-pulse rounded-full bg-blue-400/30 blur-2xl" />
                  <div className="relative flex size-40 items-center justify-center rounded-full border border-white/40 bg-white/10">
                    <KeyRound className="size-20" />
                  </div>
                </div>
                <p className="text-5xl font-black uppercase leading-tight">{t("bootstrap.waitingTitle")}</p>
                <p className="text-2xl font-semibold text-white/70">{t("bootstrap.waitingSubtitle")}</p>
              </>
            )}

            {mode === "bootstrap-success" && (
              <>
                <CheckCircle2 className="size-36" />
                <p className="text-7xl font-black uppercase">{t("bootstrap.successTitle")}</p>
                {session ? (
                  <p className="text-3xl font-semibold">
                    {t("bootstrap.enrolledEvent")}: {session.activeEventId} · {t("bootstrap.enrolledStation")}: {session.activeStationId}
                  </p>
                ) : null}
              </>
            )}

            {mode === "bootstrap-error" && (
              <>
                <AlertTriangle className="size-36" />
                <p className="text-7xl font-black uppercase">{t("bootstrap.errorTitle")}</p>
                {currentReason ? <p className="text-3xl font-semibold">{currentReason}</p> : null}
              </>
            )}

            {/* ── Ticket scanning states (enrolled) ── */}
            {mode === "idle" && (
              <>
                <div className="relative">
                  <div className="absolute inset-0 animate-pulse rounded-full bg-blue-400/30 blur-2xl" />
                  <div className="relative flex size-40 items-center justify-center rounded-full border border-white/40 bg-white/10">
                    <QrCode className="size-20" />
                  </div>
                </div>
                <p className="text-5xl font-black uppercase leading-tight">{t("operator.idleMessage")}</p>
              </>
            )}

            {mode === "success" && (
              <>
                <CheckCircle2 className="size-36" />
                <p className="text-7xl font-black uppercase">{t("operator.successMessage")}</p>
              </>
            )}

            {mode === "error" && (
              <>
                <AlertTriangle className="size-36" />
                <p className="text-7xl font-black uppercase">{t("operator.errorMessage")}</p>
                {currentReason ? <p className="text-3xl font-semibold">{currentReason}</p> : null}
              </>
            )}

            <div className="w-full max-w-3xl rounded-2xl border border-white/20 bg-black/20 p-5">
              <p className="text-xl uppercase tracking-wider text-white/75">{t("operator.currentTicket")}</p>
              <p className="mt-2 truncate text-4xl font-black">{currentTicket ?? "--"}</p>
            </div>
          </CardContent>

          {isProcessing ? (
            <div className="absolute inset-0 grid place-items-center rounded-3xl bg-slate-950/55 backdrop-blur-sm">
              <div className="flex items-center gap-3 rounded-full border border-white/25 bg-black/25 px-6 py-3 text-lg">
                <LoaderCircle className="size-5 animate-spin" />
                {t("operator.processing")}
              </div>
            </div>
          ) : null}
        </Card>

        <div className="flex max-h-[96vh] flex-col gap-4 overflow-hidden">
          {/* ── Kiosk enrollment info ── */}
          <Card className="border-white/20 bg-black/25 text-white">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between text-lg">
                <span>{t("bootstrap.sessionTitle")}</span>
                {enrolled ? (
                  <Badge variant="default" className="bg-emerald-500 text-white">
                    {t("bootstrap.statusActive")}
                  </Badge>
                ) : (
                  <Badge variant="outline">{t("bootstrap.statusInactive")}</Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 text-sm">
              {enrolled && session ? (
                <>
                  <p className="text-white/85">
                    <span className="text-white/60">{t("bootstrap.enrolledEvent")}: </span>
                    {session.activeEventId}
                  </p>
                  <p className="text-white/85">
                    <span className="text-white/60">{t("bootstrap.enrolledStation")}: </span>
                    {session.activeStationId}
                  </p>
                  <p className="text-xs text-white/60">
                    {t("bootstrap.enrolledExpiry")}:{" "}
                    {new Date(session.expiresAt * 1000).toLocaleString("es-ES")}
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleClearSession()}
                    className="mt-1 flex items-center gap-2 rounded-full border border-white/40 px-3 py-1 text-xs uppercase tracking-wide hover:bg-white/10"
                  >
                    <LogOut className="size-3" />
                    {t("bootstrap.resetSession")}
                  </button>
                </>
              ) : (
                <p className="text-sm text-white/60">{t("bootstrap.waitingSubtitle")}</p>
              )}
            </CardContent>
          </Card>

          <Card className="border-white/20 bg-black/25 text-white">
            <CardHeader>
              <CardTitle className="text-2xl">{t("operator.healthTitle")}</CardTitle>
              <CardDescription className="text-white/70">{t("operator.healthDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              <div className="flex items-center justify-between rounded-lg border border-white/20 px-3 py-2">
                <span>{t("operator.health.usb")}</span>
                <Badge variant={webhid.connected ? "default" : "outline"}>{webhid.connected ? "connected" : "disconnected"}</Badge>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/20 px-3 py-2">
                <span>{t("operator.health.device")}</span>
                <Badge variant={webhid.health === "responding" ? "default" : "secondary"}>{webhid.health}</Badge>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/20 px-3 py-2">
                <span>{t("operator.health.focus")}</span>
                <Badge variant={isWindowFocused ? "default" : "secondary"}>{isWindowFocused ? "active" : "inactive"}</Badge>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/20 px-3 py-2">
                <span>{t("operator.health.backend")}</span>
                <Badge variant={backendHealth.data?.backend_status === "red" ? "secondary" : "default"}>
                  {backendHealth.data?.backend_status ?? "unknown"}
                </Badge>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/20 px-3 py-2">
                <span>{t("operator.health.websocket")}</span>
                <Badge variant="outline">not configured</Badge>
              </div>
              <Separator className="bg-white/20" />
              <div className="rounded-lg border border-white/20 p-3">
                <p className="flex items-center gap-2 text-white/85">
                  <Usb className="size-4" />
                  {webhid.deviceLabel}
                </p>
                <p className="mt-1 text-xs text-white/70">
                  {t("operator.health.remembered")}: {webhid.rememberedDeviceCount}
                </p>
                <button
                  type="button"
                  onClick={() => void webhid.requestPermission()}
                  className="mt-2 rounded-full border border-white/40 px-3 py-1 text-xs uppercase tracking-wide hover:bg-white/10"
                >
                  {t("operator.grantPermission")}
                </button>
              </div>
            </CardContent>
          </Card>

          <Card className="border-white/20 bg-black/25 text-white">
            <CardHeader>
              <CardTitle className="text-2xl">{t("operator.metricsTitle")}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 text-sm">
              <p>{t("operator.metrics.lastMs")}: {scanHistory[0]?.responseTimeMs ?? 0} ms</p>
              <p>{t("operator.metrics.min")}: {metrics.min} ms</p>
              <p>{t("operator.metrics.max")}: {metrics.max} ms</p>
              <p>{t("operator.metrics.avg")}: {metrics.avg} ms</p>
              <p>{t("operator.metrics.successRate")}: {metrics.successRate}%</p>
              <p className="text-xs text-white/70">{metrics.history.join(", ") || "0"}</p>
            </CardContent>
          </Card>

          <Card className="min-h-0 flex-1 overflow-hidden border-white/20 bg-black/25 text-white">
            <CardHeader>
              <CardTitle className="text-2xl">{t("operator.historyTitle")}</CardTitle>
            </CardHeader>
            <CardContent className="grid h-full min-h-0 gap-3 overflow-hidden">
              <div className="grid max-h-64 gap-2 overflow-y-auto pr-1">
                {scanHistory.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedHistoryItem(item)}
                    className="grid gap-1 rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-left hover:bg-white/10"
                  >
                    <div className="flex items-center justify-between">
                      <span className="truncate font-semibold">{item.ticket}</span>
                      <Badge variant={getStatusBadgeVariant(item.status)}>{item.status}</Badge>
                    </div>
                    <p className="text-xs text-white/70">{formatClock(item.timestamp)} · {item.responseTimeMs} ms</p>
                  </button>
                ))}
                {scanHistory.length === 0 ? <p className="text-sm text-white/70">{t("operator.emptyHistory")}</p> : null}
              </div>

              {selectedHistoryItem ? (
                <div className="rounded-xl border border-white/20 bg-black/20 p-3 text-sm">
                  <p className="font-semibold">{selectedHistoryItem.ticket}</p>
                  <p>{t("operator.detail.status")}: {selectedHistoryItem.status}</p>
                  <p>{t("operator.detail.response")}: {selectedHistoryItem.responseTimeMs} ms</p>
                  <p>{t("operator.detail.time")}: {formatClock(selectedHistoryItem.timestamp)}</p>
                  <p>{t("operator.detail.wix")}: {selectedHistoryItem.wixStatus}</p>
                  <p>{t("operator.detail.errorCode")}: {selectedHistoryItem.errorCode || "none"}</p>
                  {selectedHistoryItem.reason ? <p>{t("operator.detail.error")}: {selectedHistoryItem.reason}</p> : null}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>
      </div>
    </section>
  );
}
