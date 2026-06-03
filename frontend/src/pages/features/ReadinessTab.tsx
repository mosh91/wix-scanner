import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpModal } from "@/components/HelpModal";
import { useHelpModal } from "@/hooks/useHelpModal";
import { useAdminData } from "@/context/AdminDataContext";
import { activateEvent, getEventReadiness, syncManifest } from "@/services/scannerApi";

interface ReadinessReport {
  event_id: string;
  overall_status: "ready" | "degraded" | "critical";
  component_statuses: Array<{
    name: string;
    status: "ready" | "degraded" | "critical";
    message: string;
    details: Record<string, unknown>;
  }>;
  failed_checks: string[];
  recommended_actions: string[];
  evaluated_at: string;
  readiness_acknowledged: boolean;
}

export default function ReadinessTab() {
  const { t } = useTranslation();
  const { verifiedEvents } = useAdminData();
  const help = useHelpModal();

  const [readinessEventId, setReadinessEventId] = useState("event-demo-01");
  const [readinessAcknowledged, setReadinessAcknowledged] = useState(false);
  const [readinessReport, setReadinessReport] = useState<ReadinessReport | null>(null);
  const [loadingReadiness, setLoadingReadiness] = useState(false);

  const loadReadiness = useCallback(async (eventId: string) => {
    setLoadingReadiness(true);
    try {
      const report = await getEventReadiness(eventId);
      setReadinessReport(report);
      if (report.overall_status !== "degraded") {
        setReadinessAcknowledged(true);
      }
    } catch {
      toast.error(t("home.readiness.loadError"));
    } finally {
      setLoadingReadiness(false);
    }
  }, [t]);

  useEffect(() => {
    if (verifiedEvents.length > 0) {
      const isValidSelection = verifiedEvents.some((e) => e.wix_event_id === readinessEventId);
      const eventId = isValidSelection ? readinessEventId : verifiedEvents[0].wix_event_id;
      if (eventId !== readinessEventId) {
        setReadinessEventId(eventId);
      } else {
        void loadReadiness(eventId);
      }
    }
  }, [loadReadiness, readinessEventId, verifiedEvents]);

  const handleSyncReadinessManifest = async () => {
    try {
      await syncManifest(readinessEventId);
      toast.success(t("home.readiness.syncSuccess"));
      await loadReadiness(readinessEventId);
    } catch {
      toast.error(t("home.readiness.syncError"));
    }
  };

  const handleActivateReadinessEvent = async () => {
    try {
      await activateEvent(readinessEventId, "operator-ui", readinessAcknowledged);
      toast.success(t("home.readiness.activateSuccess"));
      await loadReadiness(readinessEventId);
    } catch {
      toast.error(t("home.readiness.activateError"));
    }
  };

  return (
    <>
      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>{t("home.readiness.title")}</CardTitle>
              <CardDescription>{t("home.readiness.description")}</CardDescription>
            </div>
            <Button className="h-8 px-3 text-xs" variant="outline" onClick={help.open}>
              {t("home.readiness.helpButton")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
            <select
              className="h-10 rounded-md border border-border bg-background px-3 text-sm"
              value={readinessEventId}
              onChange={(e) => setReadinessEventId(e.target.value)}
              disabled={verifiedEvents.length === 0}
            >
              {verifiedEvents.length === 0 ? (
                <option value="">{t("home.readiness.noEvents")}</option>
              ) : (
                verifiedEvents.map((event) => (
                  <option key={event.wix_event_id} value={event.wix_event_id}>
                    {event.wix_event_name ? `${event.wix_event_name} (${event.wix_event_id})` : event.wix_event_id}
                  </option>
                ))
              )}
            </select>
            <Button onClick={() => void loadReadiness(readinessEventId)} disabled={loadingReadiness}>
              {loadingReadiness ? t("home.common.refreshing") : t("home.readiness.check")}
            </Button>
            <Button variant="outline" onClick={() => void handleSyncReadinessManifest()}>
              {t("home.readiness.syncManifest")}
            </Button>
          </div>

          {readinessReport ? (
            <div className="space-y-4">
              <div className="rounded-xl border border-border/70 bg-muted/40 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.readiness.overall")}</div>
                    <div className="text-lg font-semibold">{t(`home.readiness.statuses.${readinessReport.overall_status}`)}</div>
                  </div>
                  <Badge variant={readinessReport.overall_status === "ready" ? "default" : readinessReport.overall_status === "degraded" ? "secondary" : "outline"}>
                    {readinessReport.event_id}
                  </Badge>
                </div>
                {readinessReport.failed_checks.length > 0 ? (
                  <p className="mt-2 text-sm text-muted-foreground">
                    {t("home.readiness.failedChecks")}: {readinessReport.failed_checks
                      .map((c) => t(`home.bindings.readinessChecks.${c}`, { defaultValue: c }))
                      .join(", ")}
                  </p>
                ) : null}
                {readinessReport.recommended_actions.length > 0 ? (
                  <p className="mt-2 text-sm text-muted-foreground">
                    {t("home.readiness.recommendedActions")}: {readinessReport.recommended_actions.join(" • ")}
                  </p>
                ) : null}
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                {readinessReport.component_statuses.map((component) => (
                  <div key={component.name} className="rounded-xl border border-border/70 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-medium">{t(`home.readiness.components.${component.name}`)}</div>
                      <Badge variant={component.status === "ready" ? "default" : component.status === "degraded" ? "secondary" : "outline"}>
                        {t(`home.readiness.statuses.${component.status}`)}
                      </Badge>
                    </div>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {typeof component.details?.detail_key === "string"
                        ? t(`home.readiness.details.${component.details.detail_key}`, { defaultValue: component.message })
                        : component.message}
                    </p>
                  </div>
                ))}
              </div>

              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={readinessAcknowledged}
                  onChange={(e) => setReadinessAcknowledged(e.target.checked)}
                  disabled={readinessReport.overall_status !== "degraded"}
                />
                <span>{t("home.readiness.acknowledge")}</span>
              </label>

              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void handleActivateReadinessEvent()}>
                  {t("home.readiness.activate")}
                </Button>
                <Button variant="outline" onClick={() => void loadReadiness(readinessEventId)}>
                  {t("home.readiness.refresh")}
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("home.readiness.empty")}</p>
          )}
        </CardContent>
      </Card>

      <HelpModal
        open={help.isOpen}
        onClose={help.close}
        title={t("home.readiness.helpModal.title")}
        subtitle={t("home.readiness.helpModal.subtitle")}
      >
        <div>
          <div className="font-medium">1. {t("home.readiness.helpModal.step1Title")}</div>
          <p className="text-muted-foreground">{t("home.readiness.helpModal.step1Body")}</p>
        </div>
        <div>
          <div className="font-medium">2. {t("home.readiness.helpModal.step2Title")}</div>
          <p className="text-muted-foreground">{t("home.readiness.helpModal.step2Body")}</p>
        </div>
        <div>
          <div className="font-medium">3. {t("home.readiness.helpModal.step3Title")}</div>
          <p className="text-muted-foreground">{t("home.readiness.helpModal.step3Body")}</p>
        </div>
        <div>
          <div className="font-medium">4. {t("home.readiness.helpModal.step4Title")}</div>
          <p className="text-muted-foreground">{t("home.readiness.helpModal.step4Body")}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/40 p-4">
          <div className="font-medium">{t("home.readiness.helpModal.referenceTitle")}</div>
          <div className="mt-3 flex flex-col gap-2">
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/business-solutions/events/registration/ticketing/tickets/introduction" target="_blank" rel="noreferrer">
              {t("home.readiness.helpModal.referenceTickets")}
            </a>
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/app-management/app-instance/get-app-instance" target="_blank" rel="noreferrer">
              {t("home.readiness.helpModal.referenceInstance")}
            </a>
          </div>
        </div>
      </HelpModal>
    </>
  );
}
