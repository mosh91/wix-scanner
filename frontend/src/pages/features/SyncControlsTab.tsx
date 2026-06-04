import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpModal } from "@/components/HelpModal";
import { useHelpModal } from "@/hooks/useHelpModal";
import { useAdminData } from "@/context/AdminDataContext";
import {
  getManifestStatus,
  getSyncControl,
  syncManifest,
  upsertSyncControl,
  type ManifestSyncResponse,
  type WixSyncControlRecord,
} from "@/services/scannerApi";

export default function SyncControlsTab() {
  const { t } = useTranslation();
  const help = useHelpModal();
  const { verifiedEvents } = useAdminData();

  const [syncControlEventId, setSyncControlEventId] = useState("event-demo-01");
  const [syncControlEnabled, setSyncControlEnabled] = useState(true);
  const [syncControlInterval, setSyncControlInterval] = useState(60);
  const [syncControlStatus, setSyncControlStatus] = useState<WixSyncControlRecord | null>(null);
  const [manifestStatus, setManifestStatus] = useState<ManifestSyncResponse | null>(null);
  const [loadingSyncControl, setLoadingSyncControl] = useState(false);
  const [syncingManifest, setSyncingManifest] = useState(false);

  const loadSyncControls = useCallback(async (eventId: string) => {
    setLoadingSyncControl(true);
    try {
      const [control, manifest] = await Promise.all([
        getSyncControl(eventId),
        getManifestStatus(eventId).catch(() => null),
      ]);
      setSyncControlStatus(control);
      setSyncControlEnabled(control.enabled);
      setSyncControlInterval(control.interval_seconds);
      setManifestStatus(manifest);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.syncControls.loadError"));
    } finally {
      setLoadingSyncControl(false);
    }
  }, [t]);

  const handleSyncNow = async () => {
    setSyncingManifest(true);
    try {
      const result = await syncManifest(syncControlEventId);
      setManifestStatus(result);
      toast.success(`Sincronizado: ${result.total_tickets} tickets (${result.checked_in_tickets} ingresados)`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al sincronizar el manifest");
    } finally {
      setSyncingManifest(false);
    }
  };

  useEffect(() => {
    if (verifiedEvents.length > 0) {
      const isValidSelection = verifiedEvents.some((e) => e.wix_event_id === syncControlEventId);
      const eventId = isValidSelection ? syncControlEventId : verifiedEvents[0].wix_event_id;
      if (eventId !== syncControlEventId) {
        setSyncControlEventId(eventId);
      } else {
        void loadSyncControls(eventId);
      }
    }
  }, [loadSyncControls, syncControlEventId, verifiedEvents]);

  const handleSaveSyncControls = async () => {
    try {
      const updated = await upsertSyncControl(syncControlEventId, {
        enabled: syncControlEnabled,
        interval_seconds: syncControlInterval,
      });
      setSyncControlStatus(updated);
      toast.success(t("home.syncControls.saveSuccess"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.syncControls.saveError"));
    }
  };

  return (
    <>
      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>{t("home.syncControls.title")}</CardTitle>
              <CardDescription>{t("home.syncControls.description")}</CardDescription>
            </div>
            <Button className="h-8 px-3 text-xs" variant="outline" onClick={help.open}>
              {t("home.syncControls.helpButton")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto]">
            <select
              className="h-10 rounded-md border border-border bg-background px-3 text-sm"
              value={syncControlEventId}
              onChange={(e) => setSyncControlEventId(e.target.value)}
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
            <select
              className="h-10 rounded-md border border-border bg-background px-3 text-sm"
              value={syncControlInterval}
              onChange={(e) => setSyncControlInterval(Number(e.target.value))}
            >
              <option value={60}>{t("home.syncControls.interval60")}</option>
              <option value={90}>{t("home.syncControls.interval90")}</option>
              <option value={120}>{t("home.syncControls.interval120")}</option>
            </select>
            <label className="flex items-center gap-2 rounded-md border border-border px-3 text-sm">
              <input
                type="checkbox"
                checked={syncControlEnabled}
                onChange={(e) => setSyncControlEnabled(e.target.checked)}
              />
              <span>{syncControlEnabled ? t("home.syncControls.enabled") : t("home.syncControls.disabled")}</span>
            </label>
            <Button onClick={() => void handleSaveSyncControls()}>
              {t("home.syncControls.save")}
            </Button>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void loadSyncControls(syncControlEventId)} disabled={loadingSyncControl}>
              {loadingSyncControl ? t("home.common.refreshing") : t("home.syncControls.refresh")}
            </Button>
          </div>

          {syncControlStatus ? (
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-lg border border-border/70 bg-muted/40 p-3">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.syncControls.lastSync")}</div>
                <div className="mt-1 text-sm font-medium">
                  {syncControlStatus.last_successful_sync_at
                    ? new Date(syncControlStatus.last_successful_sync_at * 1000).toLocaleString()
                    : t("home.syncControls.never")}
                </div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/40 p-3">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.syncControls.currentLag")}</div>
                <div className="mt-1 text-sm font-medium">
                  {syncControlStatus.current_lag_seconds !== null
                    ? `${syncControlStatus.current_lag_seconds}s`
                    : t("home.syncControls.notAvailable")}
                </div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/40 p-3">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.syncControls.lastError")}</div>
                <div className="mt-1 text-sm font-medium">
                  {syncControlStatus.last_error ?? t("home.syncControls.none")}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("home.syncControls.empty")}</p>
          )}

          {manifestStatus && (
            <div className="rounded-lg border border-border bg-background p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold">Cache local de tickets</span>
                <Button size="sm" variant="outline" onClick={() => void handleSyncNow()} disabled={syncingManifest}>
                  {syncingManifest ? "Sincronizando..." : "Sincronizar ahora"}
                </Button>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-md bg-muted/50 p-3 text-center">
                  <div className="text-2xl font-bold">{manifestStatus.total_tickets}</div>
                  <div className="text-xs text-muted-foreground mt-1">Total</div>
                </div>
                <div className="rounded-md bg-emerald-50 dark:bg-emerald-950/30 p-3 text-center">
                  <div className="text-2xl font-bold text-emerald-700 dark:text-emerald-400">{manifestStatus.checked_in_tickets}</div>
                  <div className="text-xs text-muted-foreground mt-1">Ingresados</div>
                </div>
                <div className="rounded-md bg-blue-50 dark:bg-blue-950/30 p-3 text-center">
                  <div className="text-2xl font-bold text-blue-700 dark:text-blue-400">
                    {manifestStatus.total_tickets - manifestStatus.checked_in_tickets}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">Restantes</div>
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className={`inline-block size-2 rounded-full ${manifestStatus.stale ? "bg-amber-500" : "bg-emerald-500"}`} />
                {manifestStatus.stale ? "Cache desactualizada" : "Cache vigente"}
                {manifestStatus.last_known_sync_ts > 0 && (
                  <span>· Ultima sync: {new Date(manifestStatus.last_known_sync_ts * 1000).toLocaleTimeString()}</span>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <HelpModal
        open={help.isOpen}
        onClose={help.close}
        title={t("home.syncControls.helpModal.title")}
        subtitle={t("home.syncControls.helpModal.subtitle")}
      >
        <div>
          <div className="font-medium">1. {t("home.syncControls.helpModal.step1Title")}</div>
          <p className="text-muted-foreground">{t("home.syncControls.helpModal.step1Body")}</p>
        </div>
        <div>
          <div className="font-medium">2. {t("home.syncControls.helpModal.step2Title")}</div>
          <p className="text-muted-foreground">{t("home.syncControls.helpModal.step2Body")}</p>
        </div>
        <div>
          <div className="font-medium">3. {t("home.syncControls.helpModal.step3Title")}</div>
          <p className="text-muted-foreground">{t("home.syncControls.helpModal.step3Body")}</p>
        </div>
        <div>
          <div className="font-medium">4. {t("home.syncControls.helpModal.step4Title")}</div>
          <p className="text-muted-foreground">{t("home.syncControls.helpModal.step4Body")}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/40 p-4">
          <div className="font-medium">{t("home.syncControls.helpModal.referenceTitle")}</div>
          <div className="mt-3 flex flex-col gap-2">
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/business-solutions/events/registration/ticketing/tickets/introduction" target="_blank" rel="noreferrer">
              {t("home.syncControls.helpModal.referenceTickets")}
            </a>
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/business-solutions/events/skills/list-events" target="_blank" rel="noreferrer">
              {t("home.syncControls.helpModal.referenceEvents")}
            </a>
          </div>
        </div>
      </HelpModal>
    </>
  );
}
