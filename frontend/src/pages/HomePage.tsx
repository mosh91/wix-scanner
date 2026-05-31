import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  activateCredential,
  activateEvent,
  createCredential,
  createEvent,
  createBlock,
  createSiteEventBinding,
  deleteEvent,
  deleteBlock,
  fetchWebhookHistory,
  getAuthTokenStatus,
  getEventReadiness,
  listBlocks,
  listEvents,
  listReconciliationConflicts,
  listReconciliationRuns,
  listCredentials,
  listLatestScopeAudits,
  listSiteEventBindings,
  listVerifiedEvents,
  getSyncControl,
  resolveReconciliationConflict,
  runEventReconciliation,
  syncManifest,
  retryWebhookDelivery,
  refreshAuthToken,
  rotateCredential,
  testAuthConnection,
  upsertSyncControl,
  validateAuthModeConsistency,
  validateCredential,
  verifyBindingScopes,
  verifySiteEventBinding,
  resetEvent,
  listResetAudit,
  type AuthMode,
  type AuthTokenStatusResponse,
  type CredentialLifecycleRecord,
  type EventRecord,
  type EventBlockRecord,
  type ResetAuditRecord,
  type SiteEventBindingRecord,
  type ReconciliationItemRecord,
  type ReconciliationRunRecord,
  type VerifiedEventRecord,
  type WixSyncControlRecord,
  type WixScopeAuditRecord,
  type WebhookDeliveryRecord,
} from "@/services/scannerApi";

type HomeTab = "dashboard" | "integrations" | "deliveries" | "credentials" | "auth-settings" | "readiness" | "sync-controls" | "reconciliation" | "event-config";

export default function HomePage() {
  const { t } = useTranslation();
  const [webhookHistory, setWebhookHistory] = useState<WebhookDeliveryRecord[]>([]);
  const [loadingWebhooks, setLoadingWebhooks] = useState(false);
  const [bindings, setBindings] = useState<SiteEventBindingRecord[]>([]);
  const [verifiedEvents, setVerifiedEvents] = useState<VerifiedEventRecord[]>([]);
  const [loadingBindings, setLoadingBindings] = useState(false);
  const [scopeAudits, setScopeAudits] = useState<Record<string, WixScopeAuditRecord>>({});
  const [newSiteId, setNewSiteId] = useState("site-demo-01");
  const [newEventId, setNewEventId] = useState("event-demo-01");
  const [activeTab, setActiveTab] = useState<HomeTab>("dashboard");
  const [isBindingHelpOpen, setIsBindingHelpOpen] = useState(false);

  // Credential lifecycle state
  const [credentials, setCredentials] = useState<CredentialLifecycleRecord[]>([]);
  const [loadingCredentials, setLoadingCredentials] = useState(false);
  const [newProfileName, setNewProfileName] = useState("profile-01");
  const [newAuthMode, setNewAuthMode] = useState<AuthMode>("api_key");
  const [selectedCredential, setSelectedCredential] = useState<CredentialLifecycleRecord | null>(null);
  const [isValidateModalOpen, setIsValidateModalOpen] = useState(false);
  const [isRotateModalOpen, setIsRotateModalOpen] = useState(false);
  const [isCredentialsHelpOpen, setIsCredentialsHelpOpen] = useState(false);
  const [rotateNewProfile, setRotateNewProfile] = useState("");
  const [rotateNewAuthMode, setRotateNewAuthMode] = useState<AuthMode>("api_key");
  const [authTokenStatus, setAuthTokenStatus] = useState<AuthTokenStatusResponse | null>(null);
  const [loadingAuthSettings, setLoadingAuthSettings] = useState(false);
  const [readinessEventId, setReadinessEventId] = useState("event-demo-01");
  const [readinessAcknowledged, setReadinessAcknowledged] = useState(false);
  const [readinessReport, setReadinessReport] = useState<
    | {
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
    | null
  >(null);
  const [loadingReadiness, setLoadingReadiness] = useState(false);
  const [syncControlEventId, setSyncControlEventId] = useState("event-demo-01");
  const [syncControlEnabled, setSyncControlEnabled] = useState(true);
  const [syncControlInterval, setSyncControlInterval] = useState(60);
  const [syncControlStatus, setSyncControlStatus] = useState<WixSyncControlRecord | null>(null);
  const [loadingSyncControl, setLoadingSyncControl] = useState(false);
  const [reconciliationEventId, setReconciliationEventId] = useState("event-demo-01");
  const [reconciliationRuns, setReconciliationRuns] = useState<ReconciliationRunRecord[]>([]);
  const [reconciliationConflicts, setReconciliationConflicts] = useState<ReconciliationItemRecord[]>([]);
  const [loadingReconciliation, setLoadingReconciliation] = useState(false);
  const [resolvingConflictId, setResolvingConflictId] = useState<string | null>(null);

  // Event block config state
  const [eventConfigList, setEventConfigList] = useState<EventRecord[]>([]);
  const [loadingEventConfig, setLoadingEventConfig] = useState(false);
  const [selectedEventForBlocks, setSelectedEventForBlocks] = useState<string | null>(null);
  const [blockList, setBlockList] = useState<EventBlockRecord[]>([]);
  const [loadingBlocks, setLoadingBlocks] = useState(false);
  const [newEventWixId, setNewEventWixId] = useState("");
  const [newEventName, setNewEventName] = useState("");
  const [newBlockCode, setNewBlockCode] = useState("");
  const [newBlockName, setNewBlockName] = useState("");
  const [newBlockStartsAt, setNewBlockStartsAt] = useState("");
  const [newBlockEndsAt, setNewBlockEndsAt] = useState("");
  const [newBlockGracePeriod, setNewBlockGracePeriod] = useState(0);
  const [newBlockPriority, setNewBlockPriority] = useState(100);
  const [eventConfigError, setEventConfigError] = useState<string | null>(null);

  // Reset state
  const [resetTargetEventId, setResetTargetEventId] = useState<string | null>(null);
  const [resetReason, setResetReason] = useState("");
  const [resetActor, setResetActor] = useState("");
  const [resetAdminKey, setResetAdminKey] = useState("");
  const [resetInProgress, setResetInProgress] = useState(false);
  const [auditRecords, setAuditRecords] = useState<ResetAuditRecord[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);

  const loadEventConfig = useCallback(async () => {
    setLoadingEventConfig(true);
    try {
      const events = await listEvents();
      setEventConfigList(events);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load events");
    } finally {
      setLoadingEventConfig(false);
    }
  }, []);

  const loadBlocks = useCallback(async (eventId: string) => {
    setLoadingBlocks(true);
    try {
      const blocks = await listBlocks(eventId);
      setBlockList(blocks);
    } catch {
      setBlockList([]);
    } finally {
      setLoadingBlocks(false);
    }
  }, []);

  const handleCreateEvent = useCallback(async () => {
    if (!newEventWixId.trim() || !newEventName.trim()) return;
    setEventConfigError(null);
    try {
      await createEvent({ wix_event_id: newEventWixId.trim(), name: newEventName.trim(), actor: "operator-ui" });
      setNewEventWixId("");
      setNewEventName("");
      await loadEventConfig();
      toast.success("Event created");
    } catch (err) {
      setEventConfigError(err instanceof Error ? err.message : "Failed to create event");
    }
  }, [newEventWixId, newEventName, loadEventConfig]);

  const handleDeleteEvent = useCallback(async (eventId: string) => {
    try {
      await deleteEvent(eventId);
      setEventConfigList((prev) => prev.filter((e) => e.event_id !== eventId));
      if (selectedEventForBlocks === eventId) {
        setSelectedEventForBlocks(null);
        setBlockList([]);
      }
      toast.success("Event deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete event");
    }
  }, [selectedEventForBlocks]);

  const handleAddBlock = useCallback(async () => {
    if (!selectedEventForBlocks || !newBlockCode.trim() || !newBlockStartsAt || !newBlockEndsAt) return;
    setEventConfigError(null);
    try {
      await createBlock(selectedEventForBlocks, {
        block_code: newBlockCode.trim(),
        name: newBlockName.trim() || newBlockCode.trim(),
        starts_at: newBlockStartsAt,
        ends_at: newBlockEndsAt,
        grace_period_minutes: newBlockGracePeriod,
        priority: newBlockPriority,
        actor: "operator-ui",
      });
      setNewBlockCode("");
      setNewBlockName("");
      setNewBlockStartsAt("");
      setNewBlockEndsAt("");
      setNewBlockGracePeriod(0);
      setNewBlockPriority(100);
      await loadBlocks(selectedEventForBlocks);
      toast.success("Block added");
    } catch (err) {
      setEventConfigError(err instanceof Error ? err.message : "Failed to create block");
    }
  }, [selectedEventForBlocks, newBlockCode, newBlockName, newBlockStartsAt, newBlockEndsAt, newBlockGracePeriod, newBlockPriority, loadBlocks]);

  const handleDeleteBlock = useCallback(async (blockId: string) => {
    try {
      await deleteBlock(blockId);
      setBlockList((prev) => prev.filter((b) => b.block_id !== blockId));
      toast.success("Block deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete block");
    }
  }, []);

  const handleResetEvent = useCallback(async (wixEventId: string) => {
    if (!resetReason.trim() || !resetActor.trim() || !resetAdminKey.trim()) return;
    setResetInProgress(true);
    try {
      const result = await resetEvent(wixEventId, resetActor.trim(), resetReason.trim(), resetAdminKey.trim());
      toast.success(t("home.eventConfig.resetSuccess", { count: result.records_cleared }));
      setResetTargetEventId(null);
      setResetReason("");
      setResetActor("");
      // Reload audit trail
      const entries = await listResetAudit(resetAdminKey.trim());
      setAuditRecords(entries);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.eventConfig.resetError"));
    } finally {
      setResetInProgress(false);
    }
  }, [resetReason, resetActor, resetAdminKey, t]);

  const loadAuditTrail = useCallback(async () => {
    if (!resetAdminKey.trim()) return;
    setAuditError(null);
    try {
      const entries = await listResetAudit(resetAdminKey.trim());
      setAuditRecords(entries);
    } catch (err) {
      setAuditError(err instanceof Error ? err.message : t("home.eventConfig.auditLoadError"));
    }
  }, [resetAdminKey, t]);

  const dashboardStats = useMemo(() => {
    const verifiedBindings = bindings.filter((item) => item.status === "verified").length;
    const warningScopes = Object.values(scopeAudits).filter((item) => item.status === "warning").length;
    const webhookFailures = webhookHistory.filter((item) => item.status !== "delivered").length;
    return {
      verifiedBindings,
      warningScopes,
      webhookFailures,
      totalBindings: bindings.length,
      totalVerifiedEvents: verifiedEvents.length,
    };
  }, [bindings, scopeAudits, webhookHistory, verifiedEvents.length]);

  const loadWebhookHistory = useCallback(async () => {
    setLoadingWebhooks(true);
    try {
      const rows = await fetchWebhookHistory(12);
      setWebhookHistory(rows);
    } catch {
      toast.error(t("home.webhook.loadError"));
    } finally {
      setLoadingWebhooks(false);
    }
  }, [t]);

  useEffect(() => {
    void loadWebhookHistory();
  }, [loadWebhookHistory]);

  const loadBindings = useCallback(async () => {
    setLoadingBindings(true);
    try {
      const [bindingRows, verifiedRows] = await Promise.all([
        listSiteEventBindings(),
        listVerifiedEvents(),
      ]);
      setBindings(bindingRows);
      setVerifiedEvents(verifiedRows);

      const latestScopeRows = await listLatestScopeAudits();
      const map = latestScopeRows.reduce<Record<string, WixScopeAuditRecord>>((acc, row) => {
        acc[row.binding_id] = row;
        return acc;
      }, {});
      setScopeAudits(map);
    } catch {
      toast.error(t("home.bindings.loadError"));
    } finally {
      setLoadingBindings(false);
    }
  }, [t]);

  useEffect(() => {
    void loadBindings();
  }, [loadBindings]);

  const handleRetry = async (deliveryId: number) => {
    try {
      await retryWebhookDelivery(deliveryId);
      toast.success(t("home.webhook.retrySuccess"));
      await loadWebhookHistory();
    } catch {
      toast.error(t("home.webhook.retryError"));
    }
  };

  const handleCreateBinding = async () => {
    try {
      await createSiteEventBinding({
        wix_site_id: newSiteId,
        wix_event_id: newEventId,
        actor: "operator-ui",
        verify_immediately: true,
      });
      toast.success(t("home.bindings.createSuccess"));
      await loadBindings();
    } catch {
      toast.error(t("home.bindings.createError"));
    }
  };

  const handleVerifyBinding = async (bindingId: string) => {
    try {
      await verifySiteEventBinding(bindingId, "operator-ui");
      toast.success(t("home.bindings.verifySuccess"));
      await loadBindings();
    } catch {
      toast.error(t("home.bindings.verifyError"));
    }
  };

  const handleActivateEvent = async (wixEventId: string) => {
    try {
      await activateEvent(wixEventId, "operator-ui");
      toast.success(t("home.bindings.activateSuccess"));
    } catch {
      toast.error(t("home.bindings.activateError"));
    }
  };

  const handleVerifyScopes = async (bindingId: string) => {
    try {
      await verifyBindingScopes(bindingId, "security-admin-ui");
      toast.success(t("home.scopes.verifySuccess"));
      await loadBindings();
    } catch {
      toast.error(t("home.scopes.verifyError"));
    }
  };

  const loadCredentials = useCallback(async () => {
    setLoadingCredentials(true);
    try {
      const rows = await listCredentials();
      setCredentials(rows);
    } catch {
      toast.error(t("home.credentials.loadError"));
    } finally {
      setLoadingCredentials(false);
    }
  }, [t]);

  useEffect(() => {
    void loadCredentials();
  }, [loadCredentials]);

  const handleCreateCredential = async () => {
    try {
      await createCredential(newProfileName, newAuthMode, "operator-ui");
      toast.success(t("home.credentials.createSuccess"));
      await loadCredentials();
    } catch {
      toast.error(t("home.credentials.loadError"));
    }
  };

  const handleOpenValidateModal = (cred: CredentialLifecycleRecord) => {
    setSelectedCredential(cred);
    setIsValidateModalOpen(true);
  };

  const handleConfirmValidate = async () => {
    if (!selectedCredential) return;
    try {
      await validateCredential(selectedCredential.credential_id, "operator-ui");
      toast.success(t("home.credentials.validateSuccess"));
      setIsValidateModalOpen(false);
      setSelectedCredential(null);
      await loadCredentials();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.credentials.loadError"));
    }
  };

  const handleActivateCredential = async (credentialId: string) => {
    try {
      await activateCredential(credentialId, "operator-ui");
      toast.success(t("home.credentials.activateSuccess"));
      await loadCredentials();
    } catch {
      toast.error(t("home.credentials.loadError"));
    }
  };

  const handleOpenRotateModal = (cred: CredentialLifecycleRecord) => {
    setSelectedCredential(cred);
    setRotateNewProfile(cred.profile_name + "-rotated");
    setRotateNewAuthMode(cred.auth_mode);
    setIsRotateModalOpen(true);
  };

  const handleConfirmRotate = async () => {
    if (!selectedCredential) return;
    try {
      await rotateCredential(selectedCredential.credential_id, rotateNewProfile, rotateNewAuthMode, "operator-ui");
      toast.success(t("home.credentials.rotateSuccess"));
      setIsRotateModalOpen(false);
      setSelectedCredential(null);
      await loadCredentials();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.credentials.loadError"));
    }
  };

  const handleCheckAuthConsistency = async () => {
    try {
      const result = await validateAuthModeConsistency();
      if (result.ok) {
        toast.success("Auth mode is consistent");
      } else {
        toast.error(result.error ?? "Mixed auth modes detected");
      }
    } catch {
      toast.error(t("home.credentials.loadError"));
    }
  };

  const loadAuthSettings = useCallback(async () => {
    setLoadingAuthSettings(true);
    try {
      const status = await getAuthTokenStatus();
      setAuthTokenStatus(status);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.authSettings.loadError"));
    } finally {
      setLoadingAuthSettings(false);
    }
  }, [t]);

  useEffect(() => {
    if (activeTab === "auth-settings") {
      void loadAuthSettings();
    }
  }, [activeTab, loadAuthSettings]);

  const handleRefreshAuthToken = async () => {
    try {
      const status = await refreshAuthToken("operator-ui");
      setAuthTokenStatus(status);
      toast.success(t("home.authSettings.refreshSuccess"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.authSettings.refreshError"));
    }
  };

  const handleTestAuthConnection = async () => {
    try {
      const status = await testAuthConnection("operator-ui");
      setAuthTokenStatus(status);
      toast.success(t("home.authSettings.testSuccess"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.authSettings.testError"));
    }
  };

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
    if (activeTab === "readiness") {
      void loadReadiness(readinessEventId);
    }
  }, [activeTab, loadReadiness, readinessEventId]);

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

  const loadSyncControls = useCallback(async (eventId: string) => {
    setLoadingSyncControl(true);
    try {
      const control = await getSyncControl(eventId);
      setSyncControlStatus(control);
      setSyncControlEnabled(control.enabled);
      setSyncControlInterval(control.interval_seconds);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.syncControls.loadError"));
    } finally {
      setLoadingSyncControl(false);
    }
  }, [t]);

  useEffect(() => {
    if (activeTab === "sync-controls") {
      void loadSyncControls(syncControlEventId);
    }
  }, [activeTab, loadSyncControls, syncControlEventId]);

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
    if (activeTab === "reconciliation") {
      void loadReconciliationOverview(reconciliationEventId);
    }
  }, [activeTab, loadReconciliationOverview, reconciliationEventId]);

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
    <section className="space-y-5">
      <Card className="border-border/70 bg-[linear-gradient(135deg,rgba(13,40,75,0.92)_0%,rgba(25,102,165,0.92)_100%)] text-white">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Badge className="w-fit border-white/40 bg-white/15 text-white" variant="outline">
              {t("home.hero.badge")}
            </Badge>
            <Button asChild className="bg-white text-slate-900 hover:bg-white/90">
              <NavLink to="/operator">{t("home.hero.primaryAction")}</NavLink>
            </Button>
          </div>
          <CardTitle className="text-2xl md:text-3xl">{t("home.hero.title")}</CardTitle>
          <CardDescription className="text-white/80">{t("home.hero.description")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-white/20 bg-white/10 px-4 py-3">
            <div className="text-xs uppercase tracking-wide text-white/70">{t("home.metrics.verifiedBindings")}</div>
            <div className="text-2xl font-semibold">{dashboardStats.verifiedBindings}/{dashboardStats.totalBindings}</div>
          </div>
          <div className="rounded-xl border border-white/20 bg-white/10 px-4 py-3">
            <div className="text-xs uppercase tracking-wide text-white/70">{t("home.metrics.scopeWarnings")}</div>
            <div className="text-2xl font-semibold">{dashboardStats.warningScopes}</div>
          </div>
          <div className="rounded-xl border border-white/20 bg-white/10 px-4 py-3">
            <div className="text-xs uppercase tracking-wide text-white/70">{t("home.metrics.verifiedEvents")}</div>
            <div className="text-2xl font-semibold">{dashboardStats.totalVerifiedEvents}</div>
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap gap-2 rounded-2xl border border-border/70 bg-card p-2">
        {(["dashboard", "integrations", "deliveries", "credentials", "auth-settings", "readiness", "sync-controls", "reconciliation", "event-config"] as HomeTab[]).map((tab) => (
          <Button
            key={tab}
            variant={activeTab === tab ? "default" : "ghost"}
            className="rounded-xl"
            onClick={() => setActiveTab(tab)}
          >
            {t(`home.tabs.${tab}`)}
          </Button>
        ))}
      </div>

      {activeTab === "dashboard" ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="border-border/70">
            <CardHeader>
              <CardTitle>{t("home.dashboard.quickActionsTitle")}</CardTitle>
              <CardDescription>{t("home.dashboard.quickActionsDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Button asChild>
                <NavLink to="/operator">{t("home.dashboard.openOperator")}</NavLink>
              </Button>
              <Button variant="outline" onClick={() => void loadBindings()}>
                {t("home.dashboard.refreshIntegrations")}
              </Button>
              <Button variant="secondary" onClick={() => void loadWebhookHistory()}>
                {t("home.dashboard.refreshDeliveries")}
              </Button>
            </CardContent>
          </Card>

          <Card className="border-border/70 bg-muted/30">
            <CardHeader>
              <CardTitle>{t("home.dashboard.healthTitle")}</CardTitle>
              <CardDescription>{t("home.dashboard.healthDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex items-center justify-between rounded-lg border border-border/70 bg-background px-3 py-2">
                <span>{t("home.metrics.verifiedEvents")}</span>
                <Badge variant="outline">{dashboardStats.totalVerifiedEvents}</Badge>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-border/70 bg-background px-3 py-2">
                <span>{t("home.metrics.scopeWarnings")}</span>
                <Badge variant={dashboardStats.warningScopes > 0 ? "secondary" : "outline"}>{dashboardStats.warningScopes}</Badge>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-border/70 bg-background px-3 py-2">
                <span>{t("home.metrics.webhookIssues")}</span>
                <Badge variant={dashboardStats.webhookFailures > 0 ? "secondary" : "outline"}>{dashboardStats.webhookFailures}</Badge>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {activeTab === "deliveries" ? (
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle>{t("home.webhook.title")}</CardTitle>
            <CardDescription>{t("home.webhook.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-3">
              <Button variant="secondary" onClick={() => void loadWebhookHistory()} disabled={loadingWebhooks}>
                {loadingWebhooks ? t("home.common.refreshing") : t("home.common.refresh")}
              </Button>
            </div>
            {webhookHistory.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("home.webhook.empty")}</p>
            ) : (
              <div className="space-y-2">
                {webhookHistory.map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/70 p-3"
                  >
                    <div className="space-y-1 text-sm">
                      <div className="font-medium">
                        #{item.id} {item.ticket_number} - {item.status}
                      </div>
                      <div className="text-muted-foreground">
                        event: {item.wix_event_id} | source: {item.source}
                      </div>
                    </div>
                    <Button className="h-8 px-3 text-xs" variant="outline" onClick={() => void handleRetry(item.id)}>
                      {t("home.webhook.retry")}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "integrations" ? (
        <Card className="border-border/70">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>{t("home.bindings.title")}</CardTitle>
              <Button className="h-8 px-3 text-xs" variant="outline" onClick={() => setIsBindingHelpOpen(true)}>
                {t("home.bindings.helpButton")}
              </Button>
            </div>
            <CardDescription>{t("home.bindings.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto_auto]">
              <input
                className="h-10 rounded-md border border-border bg-background px-3 text-sm"
                value={newSiteId}
                onChange={(event) => setNewSiteId(event.target.value)}
                placeholder={t("home.bindings.sitePlaceholder")}
              />
              <input
                className="h-10 rounded-md border border-border bg-background px-3 text-sm"
                value={newEventId}
                onChange={(event) => setNewEventId(event.target.value)}
                placeholder={t("home.bindings.eventPlaceholder")}
              />
              <Button onClick={() => void handleCreateBinding()}>{t("home.bindings.create")}</Button>
              <Button variant="secondary" onClick={() => void loadBindings()} disabled={loadingBindings}>
                {loadingBindings ? t("home.common.refreshing") : t("home.common.refresh")}
              </Button>
            </div>

            {bindings.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("home.bindings.empty")}</p>
            ) : (
              <div className="space-y-2">
                {bindings.map((binding) => {
                  const scope = scopeAudits[binding.binding_id];
                  return (
                    <div
                      key={binding.binding_id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border/70 p-3"
                    >
                      <div className="space-y-1 text-sm">
                        <div className="font-medium">
                          {binding.wix_site_id} {"->"} {binding.wix_event_id}
                        </div>
                        <div className="text-muted-foreground">
                          {t("home.bindings.status")} {binding.status} | {t("home.bindings.app")} {binding.app_installation_status}
                        </div>
                        <div className="text-muted-foreground">
                          {t("home.scopes.label")} {scope ? scope.status : t("home.scopes.notChecked")}
                        </div>
                        {scope?.missing_scopes?.length ? (
                          <div className="text-xs text-amber-600">
                            {t("home.scopes.missing")}: {scope.missing_scopes.join(", ")}
                          </div>
                        ) : null}
                        {binding.last_verification_error ? (
                          <div className="text-xs text-red-500">{binding.last_verification_error}</div>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-2">
                        <Button className="h-8 px-3 text-xs" variant="outline" onClick={() => void handleVerifyBinding(binding.binding_id)}>
                          {t("home.bindings.verify")}
                        </Button>
                        <Button
                          className="h-8 px-3 text-xs"
                          variant="outline"
                          onClick={() => void handleVerifyScopes(binding.binding_id)}
                          disabled={binding.status !== "verified"}
                        >
                          {t("home.scopes.verify")}
                        </Button>
                        <Button
                          className="h-8 px-3 text-xs"
                          onClick={() => void handleActivateEvent(binding.wix_event_id)}
                          disabled={binding.status !== "verified"}
                        >
                          {t("home.bindings.activate")}
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="space-y-2">
              <div className="text-sm font-medium">{t("home.bindings.verifiedEvents")}</div>
              {verifiedEvents.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("home.bindings.noVerifiedEvents")}</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {verifiedEvents.map((event) => (
                    <Badge key={`${event.wix_site_id}-${event.wix_event_id}`} variant="outline">
                      {event.wix_event_id}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "credentials" ? (
        <Card className="border-border/70">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>{t("home.credentials.title")}</CardTitle>
              <Button className="h-8 px-3 text-xs" variant="outline" onClick={() => setIsCredentialsHelpOpen(true)}>
                {t("home.credentials.helpButton")}
              </Button>
            </div>
            <CardDescription>{t("home.credentials.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto]">
              <input
                className="h-10 rounded-md border border-border bg-background px-3 text-sm"
                value={newProfileName}
                onChange={(e) => setNewProfileName(e.target.value)}
                placeholder={t("home.credentials.profileNamePlaceholder")}
              />
              <select
                className="h-10 rounded-md border border-border bg-background px-3 text-sm"
                value={newAuthMode}
                onChange={(e) => setNewAuthMode(e.target.value as AuthMode)}
              >
                <option value="api_key">{t("home.credentials.authModes.api_key")}</option>
                <option value="oauth">{t("home.credentials.authModes.oauth")}</option>
              </select>
              <Button onClick={() => void handleCreateCredential()}>{t("home.credentials.create")}</Button>
              <Button variant="secondary" onClick={() => void loadCredentials()} disabled={loadingCredentials}>
                {loadingCredentials ? t("home.common.refreshing") : t("home.common.refresh")}
              </Button>
            </div>

            <Button variant="outline" className="h-8 px-3 text-xs" onClick={() => void handleCheckAuthConsistency()}>
              Check Auth Consistency
            </Button>

            {credentials.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("home.credentials.empty")}</p>
            ) : (
              <div className="space-y-2">
                {credentials.map((cred) => (
                  <div
                    key={cred.credential_id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border/70 p-3"
                  >
                    <div className="space-y-1 text-sm">
                      <div className="font-medium">{cred.profile_name}</div>
                      <div className="text-muted-foreground">
                        {t("home.credentials.authModeLabel")}: {t(`home.credentials.authModes.${cred.auth_mode}`)}
                        {" | "}
                        {t(`home.credentials.states.${cred.lifecycle_state}`)}
                      </div>
                      {cred.validation_error ? (
                        <div className="text-xs text-red-500">{cred.validation_error}</div>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        className="h-8 px-3 text-xs"
                        variant="outline"
                        onClick={() => handleOpenValidateModal(cred)}
                        disabled={cred.lifecycle_state === "revoked" || cred.lifecycle_state === "active"}
                      >
                        {t("home.credentials.validate")}
                      </Button>
                      <Button
                        className="h-8 px-3 text-xs"
                        variant="outline"
                        onClick={() => void handleActivateCredential(cred.credential_id)}
                        disabled={cred.lifecycle_state !== "validated"}
                      >
                        {t("home.credentials.activate")}
                      </Button>
                      <Button
                        className="h-8 px-3 text-xs"
                        variant="outline"
                        onClick={() => handleOpenRotateModal(cred)}
                        disabled={cred.lifecycle_state === "revoked" || cred.lifecycle_state === "failed"}
                      >
                        {t("home.credentials.rotate")}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "auth-settings" ? (
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle>{t("home.authSettings.title")}</CardTitle>
            <CardDescription>{t("home.authSettings.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void loadAuthSettings()} disabled={loadingAuthSettings}>
                {loadingAuthSettings ? t("home.common.refreshing") : t("home.common.refresh")}
              </Button>
              <Button variant="outline" onClick={() => void handleTestAuthConnection()}>
                {t("home.authSettings.testConnection")}
              </Button>
              <Button onClick={() => void handleRefreshAuthToken()}>
                {t("home.authSettings.refreshToken")}
              </Button>
            </div>

            {authTokenStatus ? (
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.authSettings.authMode")}</div>
                  <div className="mt-1 font-medium">{authTokenStatus.auth_mode}</div>
                </div>
                <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.authSettings.tokenStatus")}</div>
                  <div className="mt-1 font-medium">{authTokenStatus.token_status}</div>
                </div>
                <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.authSettings.expiresAt")}</div>
                  <div className="mt-1 font-medium">{authTokenStatus.expires_at ?? t("home.authSettings.notAvailable")}</div>
                </div>
                <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.authSettings.lastRefresh")}</div>
                  <div className="mt-1 font-medium">{authTokenStatus.last_refresh_at ?? t("home.authSettings.notAvailable")}</div>
                </div>
                <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.authSettings.lastTest")}</div>
                  <div className="mt-1 font-medium">{authTokenStatus.last_tested_at ?? t("home.authSettings.notAvailable")}</div>
                </div>
                <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.authSettings.lastError")}</div>
                  <div className="mt-1 font-medium">{authTokenStatus.last_error ?? t("home.authSettings.none")}</div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">{t("home.authSettings.empty")}</p>
            )}
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "readiness" ? (
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle>{t("home.readiness.title")}</CardTitle>
            <CardDescription>{t("home.readiness.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
              <input
                className="h-10 rounded-md border border-border bg-background px-3 text-sm"
                value={readinessEventId}
                onChange={(e) => setReadinessEventId(e.target.value)}
                placeholder={t("home.readiness.eventPlaceholder")}
              />
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
                      {t("home.readiness.failedChecks")}: {readinessReport.failed_checks.join(", ")}
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
                      <p className="mt-2 text-sm text-muted-foreground">{component.message}</p>
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
      ) : null}

      {activeTab === "sync-controls" ? (
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle>{t("home.syncControls.title")}</CardTitle>
            <CardDescription>{t("home.syncControls.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto]">
              <input
                className="h-10 rounded-md border border-border bg-background px-3 text-sm"
                value={syncControlEventId}
                onChange={(e) => setSyncControlEventId(e.target.value)}
                placeholder={t("home.syncControls.eventPlaceholder")}
              />
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
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "reconciliation" ? (
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle>{t("home.reconciliation.title")}</CardTitle>
            <CardDescription>{t("home.reconciliation.description")}</CardDescription>
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
      ) : null}

      {isCredentialsHelpOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-border bg-background shadow-xl">
            <div className="flex items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold">{t("home.credentials.helpModal.title")}</h3>
                <p className="text-sm text-muted-foreground">{t("home.credentials.helpModal.subtitle")}</p>
              </div>
              <Button className="h-8 px-3 text-xs" variant="ghost" onClick={() => setIsCredentialsHelpOpen(false)}>
                {t("home.credentials.helpModal.close")}
              </Button>
            </div>

            <div className="space-y-4 px-5 py-4 text-sm">
              <div>
                <div className="font-medium">1. {t("home.credentials.helpModal.step1Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.helpModal.step1Body")}</p>
              </div>
              <div>
                <div className="font-medium">2. {t("home.credentials.helpModal.step2Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.helpModal.step2Body")}</p>
              </div>
              <div>
                <div className="font-medium">3. {t("home.credentials.helpModal.step3Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.helpModal.step3Body")}</p>
              </div>

              <div className="rounded-xl border border-border/70 bg-muted/40 p-3">
                <div className="font-medium">{t("home.credentials.helpModal.referenceTitle")}</div>
                <p className="mt-2 text-muted-foreground">{t("home.credentials.helpModal.referenceBody")}</p>
                <a
                  className="mt-2 inline-block underline"
                  href="https://dev.wix.com/docs/api-reference/app-management/app-instance/get-app-instance"
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("home.credentials.helpModal.referenceLink")}
                </a>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {isValidateModalOpen && selectedCredential ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-background shadow-xl">
            <div className="flex items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold">{t("home.credentials.validateModal.title")}</h3>
                <p className="text-sm text-muted-foreground">{t("home.credentials.validateModal.subtitle")}</p>
              </div>
              <Button className="h-8 px-3 text-xs" variant="ghost" onClick={() => setIsValidateModalOpen(false)}>
                {t("home.credentials.validateModal.close")}
              </Button>
            </div>
            <div className="space-y-3 px-5 py-4 text-sm">
              <div>
                <div className="font-medium">1. {t("home.credentials.validateModal.step1Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.validateModal.step1Body")}</p>
              </div>
              <div>
                <div className="font-medium">2. {t("home.credentials.validateModal.step2Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.validateModal.step2Body")}</p>
              </div>
              <div>
                <div className="font-medium">3. {t("home.credentials.validateModal.step3Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.validateModal.step3Body")}</p>
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-border/70 px-5 py-3">
              <Button variant="outline" onClick={() => setIsValidateModalOpen(false)}>
                {t("home.credentials.validateModal.close")}
              </Button>
              <Button onClick={() => void handleConfirmValidate()}>
                {t("home.credentials.validateModal.confirm")}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {isRotateModalOpen && selectedCredential ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-background shadow-xl">
            <div className="flex items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold">{t("home.credentials.rotateModal.title")}</h3>
                <p className="text-sm text-muted-foreground">{t("home.credentials.rotateModal.subtitle")}</p>
              </div>
              <Button className="h-8 px-3 text-xs" variant="ghost" onClick={() => setIsRotateModalOpen(false)}>
                {t("home.credentials.rotateModal.close")}
              </Button>
            </div>
            <div className="space-y-3 px-5 py-4 text-sm">
              <div>
                <div className="font-medium">1. {t("home.credentials.rotateModal.step1Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.rotateModal.step1Body")}</p>
              </div>
              <div>
                <div className="font-medium">2. {t("home.credentials.rotateModal.step2Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.rotateModal.step2Body")}</p>
              </div>
              <div>
                <div className="font-medium">3. {t("home.credentials.rotateModal.step3Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.rotateModal.step3Body")}</p>
              </div>
              <div>
                <div className="font-medium">4. {t("home.credentials.rotateModal.step4Title")}</div>
                <p className="text-muted-foreground">{t("home.credentials.rotateModal.step4Body")}</p>
              </div>
              <div className="space-y-2 rounded-xl border border-border/70 bg-muted/30 p-3">
                <div className="text-xs font-medium text-muted-foreground">New profile name</div>
                <input
                  className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
                  value={rotateNewProfile}
                  onChange={(e) => setRotateNewProfile(e.target.value)}
                  placeholder={t("home.credentials.profileNamePlaceholder")}
                />
                <div className="text-xs font-medium text-muted-foreground">{t("home.credentials.authModeLabel")}</div>
                <select
                  className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
                  value={rotateNewAuthMode}
                  onChange={(e) => setRotateNewAuthMode(e.target.value as AuthMode)}
                >
                  <option value="api_key">{t("home.credentials.authModes.api_key")}</option>
                  <option value="oauth">{t("home.credentials.authModes.oauth")}</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-border/70 px-5 py-3">
              <Button variant="outline" onClick={() => setIsRotateModalOpen(false)}>
                {t("home.credentials.rotateModal.close")}
              </Button>
              <Button onClick={() => void handleConfirmRotate()}>
                {t("home.credentials.rotateModal.confirm")}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {activeTab === "event-config" ? (
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle>{t("home.eventConfig.title")}</CardTitle>
            <CardDescription>{t("home.eventConfig.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {eventConfigError ? (
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {eventConfigError}
              </div>
            ) : null}

            <div className="space-y-2">
              <div className="text-sm font-medium">{t("home.eventConfig.createEvent")}</div>
              <div className="flex flex-wrap gap-2">
                <input
                  className="h-9 rounded-md border border-border bg-background px-3 text-sm"
                  placeholder={t("home.eventConfig.wixEventIdPlaceholder")}
                  value={newEventWixId}
                  onChange={(e) => setNewEventWixId(e.target.value)}
                />
                <input
                  className="h-9 rounded-md border border-border bg-background px-3 text-sm"
                  placeholder={t("home.eventConfig.eventNamePlaceholder")}
                  value={newEventName}
                  onChange={(e) => setNewEventName(e.target.value)}
                />
                <Button
                  className="h-9 px-4 text-sm"
                  disabled={!newEventWixId.trim() || !newEventName.trim()}
                  onClick={() => void handleCreateEvent()}
                >
                  {t("home.eventConfig.addEvent")}
                </Button>
                <Button className="h-9 px-4 text-sm" variant="outline" onClick={() => void loadEventConfig()}>
                  {t("home.eventConfig.refresh")}
                </Button>
              </div>
            </div>

            {loadingEventConfig ? (
              <div className="py-4 text-center text-sm text-muted-foreground">{t("home.eventConfig.loading")}</div>
            ) : eventConfigList.length === 0 ? (
              <div className="py-4 text-center text-sm text-muted-foreground">{t("home.eventConfig.empty")}</div>
            ) : (
              <div className="divide-y divide-border/60 rounded-xl border border-border/70">
                {eventConfigList.map((ev) => (
                  <div key={ev.event_id} className="px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium">{ev.name}</div>
                        <div className="text-xs text-muted-foreground">{ev.wix_event_id} · v{ev.version}</div>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          className="h-7 px-3 text-xs"
                          variant="outline"
                          onClick={() => {
                            setSelectedEventForBlocks(ev.event_id);
                            void loadBlocks(ev.event_id);
                          }}
                        >
                          {t("home.eventConfig.viewBlocks")}
                        </Button>
                        <Button
                          className="h-7 px-3 text-xs"
                          variant="outline"
                          onClick={() => setResetTargetEventId(resetTargetEventId === ev.wix_event_id ? null : ev.wix_event_id)}
                        >
                          {t("home.eventConfig.resetEventLabel")}
                        </Button>
                        <Button
                          className="h-7 px-3 text-xs"
                          variant="ghost"
                          onClick={() => void handleDeleteEvent(ev.event_id)}
                        >
                          {t("home.eventConfig.deleteEvent")}
                        </Button>
                      </div>
                    </div>

                    {resetTargetEventId === ev.wix_event_id ? (
                      <div className="mt-3 space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
                        <div className="text-xs font-medium text-destructive">{t("home.eventConfig.resetConfirmTitle")}</div>
                        <p className="text-xs text-muted-foreground">{t("home.eventConfig.resetConfirmDescription")}</p>
                        <div className="flex flex-wrap gap-2">
                          <input
                            className="h-8 flex-1 rounded border border-border bg-background px-2 text-xs"
                            placeholder={t("home.eventConfig.resetReasonPlaceholder")}
                            title={t("home.eventConfig.resetReasonLabel")}
                            value={resetReason}
                            onChange={(e) => setResetReason(e.target.value)}
                          />
                          <input
                            className="h-8 rounded border border-border bg-background px-2 text-xs"
                            placeholder={t("home.eventConfig.resetActorPlaceholder")}
                            title={t("home.eventConfig.resetActorLabel")}
                            value={resetActor}
                            onChange={(e) => setResetActor(e.target.value)}
                          />
                          <input
                            className="h-8 rounded border border-border bg-background px-2 text-xs"
                            placeholder={t("home.eventConfig.resetAdminKeyPlaceholder")}
                            title={t("home.eventConfig.resetAdminKeyLabel")}
                            type="password"
                            value={resetAdminKey}
                            onChange={(e) => setResetAdminKey(e.target.value)}
                          />
                          <Button
                            className="h-8 border-red-500/40 px-3 text-xs text-red-600 hover:bg-red-500/10"
                            variant="outline"
                            disabled={resetInProgress || !resetReason.trim() || !resetActor.trim() || !resetAdminKey.trim()}
                            onClick={() => void handleResetEvent(ev.wix_event_id)}
                          >
                            {t("home.eventConfig.resetConfirmButton")}
                          </Button>
                          <Button
                            className="h-8 px-3 text-xs"
                            variant="ghost"
                            onClick={() => setResetTargetEventId(null)}
                          >
                            {t("home.eventConfig.resetCancelButton")}
                          </Button>
                        </div>
                      </div>
                    ) : null}

                    {selectedEventForBlocks === ev.event_id ? (
                      <div className="mt-3 space-y-3 rounded-lg border border-border/50 bg-muted/20 p-3">
                        <div className="text-xs font-medium text-muted-foreground">{t("home.eventConfig.blocks")}</div>
                        <div className="flex flex-wrap gap-2">
                          <input
                            className="h-8 rounded border border-border bg-background px-2 text-xs"
                            placeholder={t("home.eventConfig.blockCodePlaceholder")}
                            value={newBlockCode}
                            onChange={(e) => setNewBlockCode(e.target.value)}
                          />
                          <input
                            className="h-8 rounded border border-border bg-background px-2 text-xs"
                            placeholder={t("home.eventConfig.blockNamePlaceholder")}
                            value={newBlockName}
                            onChange={(e) => setNewBlockName(e.target.value)}
                          />
                          <input
                            className="h-8 rounded border border-border bg-background px-2 text-xs"
                            type="datetime-local"
                            value={newBlockStartsAt}
                            onChange={(e) => setNewBlockStartsAt(e.target.value)}
                          />
                          <input
                            className="h-8 rounded border border-border bg-background px-2 text-xs"
                            type="datetime-local"
                            value={newBlockEndsAt}
                            onChange={(e) => setNewBlockEndsAt(e.target.value)}
                          />
                          <input
                            className="h-8 w-24 rounded border border-border bg-background px-2 text-xs"
                            type="number"
                            min={0}
                            max={120}
                            placeholder={t("home.eventConfig.gracePeriodPlaceholder")}
                            title={t("home.eventConfig.gracePeriodLabel")}
                            value={newBlockGracePeriod}
                            onChange={(e) => setNewBlockGracePeriod(Number(e.target.value))}
                          />
                          <input
                            className="h-8 w-20 rounded border border-border bg-background px-2 text-xs"
                            type="number"
                            min={0}
                            placeholder={t("home.eventConfig.priorityPlaceholder")}
                            title={t("home.eventConfig.priorityLabel")}
                            value={newBlockPriority}
                            onChange={(e) => setNewBlockPriority(Number(e.target.value))}
                          />
                          <Button
                            className="h-8 px-3 text-xs"
                            disabled={!newBlockCode.trim() || !newBlockStartsAt || !newBlockEndsAt}
                            onClick={() => void handleAddBlock()}
                          >
                            {t("home.eventConfig.addBlock")}
                          </Button>
                        </div>

                        {loadingBlocks ? (
                          <div className="text-xs text-muted-foreground">{t("home.eventConfig.loading")}</div>
                        ) : blockList.length === 0 ? (
                          <div className="text-xs text-muted-foreground">{t("home.eventConfig.noBlocks")}</div>
                        ) : (
                          <div className="divide-y divide-border/40 rounded-lg border border-border/40">
                            {blockList.map((bl) => (
                              <div key={bl.block_id} className="flex items-center justify-between px-3 py-2 text-xs">
                                <div>
                                  <span className="font-medium">{bl.name}</span>
                                  <span className="ml-2 text-muted-foreground">{t("home.eventConfig.gracePeriodLabel")}: {bl.grace_period_minutes}m</span>
                                  <span className="ml-2 text-muted-foreground">{t("home.eventConfig.priorityLabel")}: {bl.priority}</span>
                                  <span className="ml-2 text-muted-foreground">[{bl.block_code}]</span>
                                  <span className="ml-2 text-muted-foreground">
                                    {bl.starts_at} → {bl.ends_at}
                                  </span>
                                </div>
                                <Button
                                  className="h-6 px-2 text-xs"
                                  variant="ghost"
                                  onClick={() => void handleDeleteBlock(bl.block_id)}
                                >
                                  {t("home.eventConfig.deleteBlock")}
                                </Button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}

            {/* Reset Audit Trail */}
            <div className="space-y-2 pt-2 border-t border-border/40">
              <div className="flex items-center gap-2">
                <div className="text-sm font-medium">{t("home.eventConfig.auditTrailLabel")}</div>
                <div className="flex gap-2">
                  <input
                    className="h-7 rounded border border-border bg-background px-2 text-xs"
                    placeholder={t("home.eventConfig.resetAdminKeyPlaceholder")}
                    title={t("home.eventConfig.resetAdminKeyLabel")}
                    type="password"
                    value={resetAdminKey}
                    onChange={(e) => setResetAdminKey(e.target.value)}
                  />
                  <Button className="h-7 px-3 text-xs" variant="outline" onClick={() => void loadAuditTrail()}>
                    {t("home.common.refresh")}
                  </Button>
                </div>
              </div>
              {auditError ? (
                <div className="text-xs text-destructive">{auditError}</div>
              ) : auditRecords.length === 0 ? (
                <div className="text-xs text-muted-foreground">{t("home.eventConfig.auditEmpty")}</div>
              ) : (
                <div className="divide-y divide-border/40 rounded-lg border border-border/40">
                  {auditRecords.map((rec) => (
                    <div key={rec.reset_id} className="grid grid-cols-[auto_1fr] gap-x-3 px-3 py-2 text-xs">
                      <span className="text-muted-foreground">{new Date(rec.performed_at).toLocaleString()}</span>
                      <span>
                        <span className="font-medium">{rec.scope}</span>
                        {" · "}
                        <span className="text-muted-foreground">{rec.scope_id}</span>
                        {" · "}
                        {rec.actor}
                        {" — "}
                        {rec.reason}
                        {" ("}
                        <span className="font-medium">{rec.records_cleared}</span>
                        {" cleared)"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {isBindingHelpOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-border bg-background shadow-xl">
            <div className="flex items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold">{t("home.bindingHelp.title")}</h3>
                <p className="text-sm text-muted-foreground">{t("home.bindingHelp.subtitle")}</p>
              </div>
              <Button className="h-8 px-3 text-xs" variant="ghost" onClick={() => setIsBindingHelpOpen(false)}>
                {t("home.bindingHelp.close")}
              </Button>

            </div>

            <div className="space-y-4 px-5 py-4 text-sm">
              <div>
                <div className="font-medium">1. {t("home.bindingHelp.step1Title")}</div>
                <p className="text-muted-foreground">{t("home.bindingHelp.step1Body")}</p>
              </div>
              <div>
                <div className="font-medium">2. {t("home.bindingHelp.step2Title")}</div>
                <p className="text-muted-foreground">{t("home.bindingHelp.step2Body")}</p>
              </div>
              <div>
                <div className="font-medium">3. {t("home.bindingHelp.step3Title")}</div>
                <p className="text-muted-foreground">{t("home.bindingHelp.step3Body")}</p>
              </div>
              <div>
                <div className="font-medium">4. {t("home.bindingHelp.step4Title")}</div>
                <p className="text-muted-foreground">{t("home.bindingHelp.step4Body")}</p>
              </div>

              <div className="rounded-xl border border-border/70 bg-muted/40 p-3">
                <div className="font-medium">{t("home.bindingHelp.referenceTitle")}</div>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
                  <li>
                    <a
                      className="underline"
                      href="https://dev.wix.com/docs/api-reference/business-management/app-installation/skills/list-installed-apps"
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("home.bindingHelp.referenceApps")}
                    </a>
                  </li>
                  <li>
                    <a
                      className="underline"
                      href="https://dev.wix.com/docs/api-reference/business-solutions/events/skills/list-events"
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("home.bindingHelp.referenceEvents")}
                    </a>
                  </li>
                  <li>
                    <a
                      className="underline"
                      href="https://dev.wix.com/docs/api-reference/app-management/app-instance/get-app-instance"
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("home.bindingHelp.referenceInstance")}
                    </a>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
