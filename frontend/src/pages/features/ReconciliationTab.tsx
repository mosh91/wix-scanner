import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpModal } from "@/components/HelpModal";
import { useHelpModal } from "@/hooks/useHelpModal";
import {
  listReconciliationConflicts,
  listReconciliationRuns,
  resolveReconciliationConflict,
  runEventReconciliation,
  type ReconciliationItemRecord,
  type ReconciliationRunRecord,
} from "@/services/scannerApi";

export default function ReconciliationTab() {
  const { t } = useTranslation();
  const help = useHelpModal();

  const [reconciliationEventId, setReconciliationEventId] = useState("event-demo-01");
  const [reconciliationRuns, setReconciliationRuns] = useState<ReconciliationRunRecord[]>([]);
  const [reconciliationConflicts, setReconciliationConflicts] = useState<ReconciliationItemRecord[]>([]);
  const [loadingReconciliation, setLoadingReconciliation] = useState(false);
  const [resolvingConflictId, setResolvingConflictId] = useState<string | null>(null);

  const loadReconciliationOverview = useCallback(async (eventId: string) => {
    setLoadingReconciliation(true);
    try {
      const runs = await listReconciliationRuns(eventId, 10);
      setReconciliationRuns(runs);
      const latestRunId = runs[0]?.run_id;
      const conflicts = await listReconciliationConflicts(eventId, latestRunId, 100);
      setReconciliationConflicts(conflicts);
    } catch {
      toast.error(t("home.reconciliation.loadError"));
    } finally {
      setLoadingReconciliation(false);
    }
  }, [t]);

  useEffect(() => {
    void loadReconciliationOverview(reconciliationEventId);
  }, [loadReconciliationOverview, reconciliationEventId]);

  const handleRunReconciliation = async () => {
    try {
      const response = await runEventReconciliation(reconciliationEventId, "operator-ui");
      setReconciliationRuns((current) => [response.run, ...current.filter((run) => run.run_id !== response.run.run_id)]);
      setReconciliationConflicts(response.items.filter((item) => item.reconciliation_state === "conflict"));
      toast.success(t("home.reconciliation.runSuccess"));
    } catch {
      toast.error(t("home.reconciliation.runError"));
    }
  };

  const handleResolveConflict = async (itemId: string, resolution: "accept_wix" | "keep_local") => {
    setResolvingConflictId(itemId);
    try {
      await resolveReconciliationConflict(itemId, resolution, "operator-ui");
      toast.success(t("home.reconciliation.resolveSuccess"));
      await loadReconciliationOverview(reconciliationEventId);
    } catch {
      toast.error(t("home.reconciliation.resolveError"));
    } finally {
      setResolvingConflictId(null);
    }
  };

  return (
    <>
      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>{t("home.reconciliation.title")}</CardTitle>
              <CardDescription>{t("home.reconciliation.description")}</CardDescription>
            </div>
            <Button className="h-8 px-3 text-xs" variant="outline" onClick={help.open}>
              {t("home.reconciliation.helpButton")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
            <input
              className="h-10 rounded-md border border-border bg-background px-3 text-sm"
              value={reconciliationEventId}
              onChange={(e) => setReconciliationEventId(e.target.value)}
              placeholder={t("home.reconciliation.eventPlaceholder")}
            />
            <Button onClick={() => void handleRunReconciliation()} disabled={loadingReconciliation}>
              {t("home.reconciliation.run")}
            </Button>
            <Button variant="outline" onClick={() => void loadReconciliationOverview(reconciliationEventId)} disabled={loadingReconciliation}>
              {loadingReconciliation ? t("home.common.refreshing") : t("home.reconciliation.refresh")}
            </Button>
          </div>

          {reconciliationRuns.length > 0 ? (
            <div className="rounded-xl border border-border/70 bg-muted/40 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.reconciliation.latestRun")}</div>
                  <div className="text-lg font-semibold">{reconciliationRuns[0].run_id.slice(0, 8)}</div>
                </div>
                <Badge variant={reconciliationRuns[0].reconciliation_state === "in_sync" ? "default" : reconciliationRuns[0].reconciliation_state === "conflict" ? "secondary" : "outline"}>
                  {t(`home.reconciliation.states.${reconciliationRuns[0].reconciliation_state}`)}
                </Badge>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                {t("home.reconciliation.driftCount")}: {reconciliationRuns[0].drift_count} | {t("home.reconciliation.resolvedCount")}: {reconciliationRuns[0].resolved_count} | {t("home.reconciliation.conflictCount")}: {reconciliationRuns[0].conflict_count}
              </p>
            </div>
          ) : null}

          <div className="space-y-2">
            <div className="text-sm font-medium">{t("home.reconciliation.conflictConsole")}</div>
            {reconciliationConflicts.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("home.reconciliation.noConflicts")}</p>
            ) : (
              <div className="space-y-2">
                {reconciliationConflicts.map((item) => (
                  <div key={item.item_id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border/70 p-3">
                    <div className="space-y-1 text-sm">
                      <div className="font-medium">{item.ticket_number}</div>
                      <div className="text-muted-foreground">
                        {t("home.reconciliation.localResult")}: {item.local_result ?? "-"} | {t("home.reconciliation.wixResult")}: {item.wix_result ?? "-"}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        className="h-8 px-3 text-xs"
                        variant="outline"
                        onClick={() => void handleResolveConflict(item.item_id, "accept_wix")}
                        disabled={resolvingConflictId === item.item_id}
                      >
                        {t("home.reconciliation.acceptWix")}
                      </Button>
                      <Button
                        className="h-8 px-3 text-xs"
                        variant="outline"
                        onClick={() => void handleResolveConflict(item.item_id, "keep_local")}
                        disabled={resolvingConflictId === item.item_id}
                      >
                        {t("home.reconciliation.keepLocal")}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <HelpModal
        open={help.isOpen}
        onClose={help.close}
        title={t("home.reconciliation.helpModal.title")}
        subtitle={t("home.reconciliation.helpModal.subtitle")}
      >
        <div>
          <div className="font-medium">1. {t("home.reconciliation.helpModal.step1Title")}</div>
          <p className="text-muted-foreground">{t("home.reconciliation.helpModal.step1Body")}</p>
        </div>
        <div>
          <div className="font-medium">2. {t("home.reconciliation.helpModal.step2Title")}</div>
          <p className="text-muted-foreground">{t("home.reconciliation.helpModal.step2Body")}</p>
        </div>
        <div>
          <div className="font-medium">3. {t("home.reconciliation.helpModal.step3Title")}</div>
          <p className="text-muted-foreground">{t("home.reconciliation.helpModal.step3Body")}</p>
        </div>
        <div>
          <div className="font-medium">4. {t("home.reconciliation.helpModal.step4Title")}</div>
          <p className="text-muted-foreground">{t("home.reconciliation.helpModal.step4Body")}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/40 p-4">
          <div className="font-medium">{t("home.reconciliation.helpModal.referenceTitle")}</div>
          <div className="mt-3 flex flex-col gap-2">
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/business-solutions/events/registration/ticketing/tickets/introduction" target="_blank" rel="noreferrer">
              {t("home.reconciliation.helpModal.referenceTickets")}
            </a>
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/business-solutions/events/skills/list-events" target="_blank" rel="noreferrer">
              {t("home.reconciliation.helpModal.referenceEvents")}
            </a>
          </div>
        </div>
      </HelpModal>
    </>
  );
}
