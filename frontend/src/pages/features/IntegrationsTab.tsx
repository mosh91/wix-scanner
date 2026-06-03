import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { BlockForm, type BlockFormData } from "@/components/BlockForm";
import { useHelpModal } from "@/hooks/useHelpModal";
import { useAdminData } from "@/context/AdminDataContext";
import {
  activateEvent,
  ActivateEventBlockedError,
  autobindIntegrations,
  createBlock,
  createEvent,
  createSiteEventBinding,
  deleteBlock,
  deleteEvent,
  listBlocks,
  listEvents,
  listResetAudit,
  listSiteEventBindings,
  listWixEvents,
  resetEvent,
  verifyBindingScopes,
  verifySiteEventBinding,
  type EventBlockRecord,
  type EventRecord,
  type ResetAuditRecord,
  type WixEventPreview,
} from "@/services/scannerApi";

export default function IntegrationsTab() {
  const { t } = useTranslation();
  const {
    bindings,
    setBindings,
    scopeAudits,
    loadingBindings,
    loadBindings,
    selectedAuthMode,
  } = useAdminData();
  const bindingHelp = useHelpModal();

  const [newSiteId, setNewSiteId] = useState("site-demo-01");
  const [newEventId, setNewEventId] = useState("event-demo-01");
  const [isAuthModeGuideExpanded, setIsAuthModeGuideExpanded] = useState(false);
  const [isAutobinding, setIsAutobinding] = useState(false);
  const [showCreateForms, setShowCreateForms] = useState(false);
  const [isAutobindModalOpen, setIsAutobindModalOpen] = useState(false);
  const [selectedAutobindEventIds, setSelectedAutobindEventIds] = useState<Set<string>>(new Set());
  const [loadingAutobindModal, setLoadingAutobindModal] = useState(false);
  const [wixEventPreviewList, setWixEventPreviewList] = useState<WixEventPreview[]>([]);
  const [eventToDelete, setEventToDelete] = useState<{ event_id: string; name: string } | null>(null);

  // Event block config
  const [eventConfigList, setEventConfigList] = useState<EventRecord[]>([]);
  const [loadingEventConfig, setLoadingEventConfig] = useState(false);
  const [selectedEventForBlocks, setSelectedEventForBlocks] = useState<string | null>(null);
  const [blocksMap, setBlocksMap] = useState<Record<string, EventBlockRecord[]>>({});
  const [loadingBlocksMap, setLoadingBlocksMap] = useState<Record<string, boolean>>({});
  const [newEventWixId, setNewEventWixId] = useState("");
  const [newEventName, setNewEventName] = useState("");
  const [eventConfigError, setEventConfigError] = useState<string | null>(null);

  // Reset
  const [resetTargetEventId, setResetTargetEventId] = useState<string | null>(null);
  const [resetReason, setResetReason] = useState("");
  const [resetActor, setResetActor] = useState("");
  const [resetAdminKey, setResetAdminKey] = useState("");
  const [resetInProgress, setResetInProgress] = useState(false);
  const [auditRecords, setAuditRecords] = useState<ResetAuditRecord[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);

  const loadBlocks = useCallback(async (eventId: string) => {
    setLoadingBlocksMap((prev) => ({ ...prev, [eventId]: true }));
    try {
      const blocks = await listBlocks(eventId);
      setBlocksMap((prev) => ({ ...prev, [eventId]: blocks }));
    } catch {
      setBlocksMap((prev) => ({ ...prev, [eventId]: [] }));
    } finally {
      setLoadingBlocksMap((prev) => ({ ...prev, [eventId]: false }));
    }
  }, []);

  const loadEventConfig = useCallback(async () => {
    setLoadingEventConfig(true);
    try {
      const events = await listEvents();
      setEventConfigList(events);
      await Promise.all(events.map((ev) => loadBlocks(ev.event_id)));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load events");
    } finally {
      setLoadingEventConfig(false);
    }
  }, [loadBlocks]);

  useEffect(() => {
    void loadEventConfig();
  }, [loadEventConfig]);

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
      setBlocksMap((prev) => {
        const next = { ...prev };
        delete next[eventId];
        return next;
      });
      if (selectedEventForBlocks === eventId) setSelectedEventForBlocks(null);
      toast.success("Event deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete event");
    }
  }, [selectedEventForBlocks]);

  const handleAddBlock = useCallback(async (eventId: string, data: BlockFormData) => {
    setEventConfigError(null);
    try {
      await createBlock(eventId, data);
      setSelectedEventForBlocks(null);
      await loadBlocks(eventId);
      toast.success("Block added");
    } catch (err) {
      setEventConfigError(err instanceof Error ? err.message : "Failed to create block");
    }
  }, [loadBlocks]);

  const handleDeleteBlock = useCallback(async (blockId: string, eventId: string) => {
    try {
      await deleteBlock(blockId);
      setBlocksMap((prev) => ({
        ...prev,
        [eventId]: (prev[eventId] ?? []).filter((b) => b.block_id !== blockId),
      }));
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

  const mergedEventRows = useMemo(() => {
    type MergedRow = {
      wixEventId: string;
      displayName: string;
      binding: typeof bindings[0] | null;
      eventConfig: typeof eventConfigList[0] | null;
    };
    const map = new Map<string, MergedRow>();
    for (const b of bindings) {
      map.set(b.wix_event_id, {
        wixEventId: b.wix_event_id,
        displayName: b.wix_event_name ?? b.wix_event_id,
        binding: b,
        eventConfig: null,
      });
    }
    for (const ev of eventConfigList) {
      const existing = map.get(ev.wix_event_id);
      if (existing) {
        existing.eventConfig = ev;
        if (ev.name) existing.displayName = ev.name;
      } else {
        map.set(ev.wix_event_id, {
          wixEventId: ev.wix_event_id,
          displayName: ev.name,
          binding: null,
          eventConfig: ev,
        });
      }
    }
    return Array.from(map.values());
  }, [bindings, eventConfigList]);

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

  const handleAutobind = async () => {
    if (isAutobinding) {
      return;
    }
    setIsAutobinding(true);
    try {
      const result = await autobindIntegrations("operator-ui");
      setNewSiteId(result.site_id);
      if (result.event_ids[0]) {
        setNewEventId(result.event_ids[0]);
      }
      await Promise.all([loadBindings(), loadEventConfig()]);
      toast.success(
        result.site_display_name
          ? `${result.site_display_name}: ${result.bindings_verified}/${result.events_found} events bound`
          : `${result.bindings_verified}/${result.events_found} events bound`,
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to autobind Wix integrations");
    } finally {
      setIsAutobinding(false);
    }
  };

  const handleOpenAutobindModal = async () => {
    setIsAutobindModalOpen(true);
    setLoadingAutobindModal(true);
    try {
      const [wixData, currentBindings] = await Promise.all([listWixEvents(), listSiteEventBindings()]);
      setWixEventPreviewList(wixData.events);
      setBindings(currentBindings);
      const boundWixIds = new Set(currentBindings.map((b) => b.wix_event_id));
      setSelectedAutobindEventIds(new Set(wixData.events.filter((e) => !boundWixIds.has(e.wix_event_id)).map((e) => e.wix_event_id)));
    } catch {
      toast.error(t("home.bindings.loadError"));
    } finally {
      setLoadingAutobindModal(false);
    }
  };

  const handleConfirmAutobindModal = async () => {
    if (selectedAutobindEventIds.size === 0) return;
    try {
      const autobindResult = await autobindIntegrations("operator-ui", true);
      const siteId = bindings[0]?.wix_site_id || autobindResult.site_id;
      await Promise.all(
        [...selectedAutobindEventIds].map((wixEventId) =>
          createSiteEventBinding({ wix_site_id: siteId, wix_event_id: wixEventId, actor: "operator-ui", verify_immediately: true }),
        ),
      );
      toast.success(t("home.bindings.createSuccess"));
      await Promise.all([loadBindings(), loadEventConfig()]);
    } catch {
      toast.error(t("home.bindings.createError"));
    } finally {
      setIsAutobindModalOpen(false);
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
    } catch (err) {
      if (err instanceof ActivateEventBlockedError && err.failedChecks.length > 0) {
        const checks = err.failedChecks
          .map((c) => t(`home.bindings.readinessChecks.${c}`, { defaultValue: c }))
          .join(", ");
        toast.error(t("home.bindings.activateBlocked", { checks }));
      } else {
        toast.error(t("home.bindings.activateError"));
      }
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

  return (
    <>
      <div className="grid gap-4 xl:grid-cols-[1.15fr_1fr]">
        <Card className="border-border/70 bg-[linear-gradient(145deg,rgba(255,255,255,1)_0%,rgba(241,245,249,0.8)_100%)]">
          <CardHeader>
            <CardTitle>{t("home.bindings.title")}</CardTitle>
            <CardDescription>{t("home.bindings.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void handleOpenAutobindModal()} disabled={isAutobinding || loadingAutobindModal}>
                {loadingAutobindModal ? t("home.bindings.autobinding") : t("home.bindings.autobind")}
              </Button>
              <Button variant="secondary" onClick={() => void loadBindings()} disabled={loadingBindings}>
                {loadingBindings ? t("home.common.refreshing") : t("home.common.refresh")}
              </Button>
            </div>

            <div className="rounded-xl border border-border/70 bg-muted/20 p-4 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="text-xs uppercase tracking-wide text-muted-foreground">
                    {t("home.authModeGuide.currentMode")}
                  </div>
                  <div className="mt-1 font-medium">
                    {selectedAuthMode ? t(`home.authModeGuide.modes.${selectedAuthMode}`) : t("home.authModeGuide.loading")}
                  </div>
                  <Badge variant="outline">.env</Badge>
                </div>
                <Button
                  className="h-8 px-3 text-xs"
                  variant="ghost"
                  onClick={() => setIsAuthModeGuideExpanded((current) => !current)}
                >
                  {isAuthModeGuideExpanded ? t("home.authModeGuide.collapseButton") : t("home.authModeGuide.expandButton")}
                </Button>
              </div>

              {isAuthModeGuideExpanded ? (
                <>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <div className="rounded-lg border border-border/70 bg-background p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        {t("home.authModeGuide.oauthTitle")}
                      </div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        {t("home.authModeGuide.oauthBody")}
                      </div>
                      <div className="mt-2 text-xs font-medium">
                        WIX_SCANNER_CREDENTIAL_PROVIDER_MODE=oauth
                      </div>
                      <div className="text-xs text-muted-foreground">
                        WIX_SCANNER_WIX_APP_ID, WIX_SCANNER_WIX_APP_SECRET, WIX_SCANNER_WIX_APP_INSTANCE_ID
                      </div>
                    </div>
                    <div className="rounded-lg border border-border/70 bg-background p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        {t("home.authModeGuide.apiKeyTitle")}
                      </div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        {t("home.authModeGuide.apiKeyBody")}
                      </div>
                      <div className="mt-2 text-xs font-medium">
                        WIX_SCANNER_CREDENTIAL_PROVIDER_MODE=env
                      </div>
                      <div className="text-xs text-muted-foreground">
                        WIX_SCANNER_WIX_API_TOKEN
                      </div>
                    </div>
                  </div>

                  <p className="mt-3 text-xs text-muted-foreground">
                    {t("home.authModeGuide.switchHint")}
                  </p>
                </>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <Card className="border-border/70 bg-muted/30">
          <CardHeader>
            <CardTitle>{t("home.setup.flowTitle")}</CardTitle>
            <CardDescription>{t("home.setup.flowDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="rounded-lg border border-border/70 bg-background px-3 py-2">1. {t("home.setup.flowStep1")}</div>
            <div className="rounded-lg border border-border/70 bg-background px-3 py-2">2. {t("home.setup.flowStep2")}</div>
            <div className="rounded-lg border border-border/70 bg-background px-3 py-2">3. {t("home.setup.flowStep3")}</div>
            <div className="rounded-lg border border-border/70 bg-background px-3 py-2">4. {t("home.setup.flowStep4")}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>{t("home.integrations.eventsTitle")}</CardTitle>
              <CardDescription>{t("home.integrations.eventsDescription")}</CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button className="h-8 px-3 text-xs" variant="outline" onClick={bindingHelp.open}>
                {t("home.bindings.helpButton")}
              </Button>
              <Button className="h-8 px-3 text-xs" variant="outline" onClick={() => void handleAutobind()} disabled={isAutobinding}>
                {isAutobinding ? t("home.bindings.autobinding") : t("home.bindings.autobind")}
              </Button>
              <Button
                className="h-8 px-3 text-xs"
                variant={showCreateForms ? "secondary" : "outline"}
                onClick={() => setShowCreateForms((v) => !v)}
              >
                {t("home.integrations.addEvent")}
              </Button>
              <Button
                className="h-8 px-3 text-xs"
                variant="ghost"
                onClick={() => { void loadBindings(); void loadEventConfig(); }}
                disabled={loadingBindings || loadingEventConfig}
              >
                {(loadingBindings || loadingEventConfig) ? t("home.common.refreshing") : t("home.common.refresh")}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Create forms */}
          {showCreateForms ? (
            <div className="grid gap-4 rounded-lg border border-border/60 bg-muted/30 p-4 md:grid-cols-2">
              <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("home.bindings.create")}</div>
                <div className="flex flex-wrap gap-2">
                  <input
                    className="h-9 flex-1 rounded-md border border-border bg-background px-3 text-sm"
                    value={newSiteId}
                    onChange={(e) => setNewSiteId(e.target.value)}
                    placeholder={t("home.bindings.sitePlaceholder")}
                  />
                  <input
                    className="h-9 flex-1 rounded-md border border-border bg-background px-3 text-sm"
                    value={newEventId}
                    onChange={(e) => setNewEventId(e.target.value)}
                    placeholder={t("home.bindings.eventPlaceholder")}
                  />
                  <Button className="h-9 px-4 text-sm" onClick={() => void handleCreateBinding()}>
                    {t("home.bindings.create")}
                  </Button>
                </div>
              </div>
              <div className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t("home.eventConfig.createEvent")}</div>
                {eventConfigError ? (
                  <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    {eventConfigError}
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <input
                    className="h-9 flex-1 rounded-md border border-border bg-background px-3 text-sm"
                    placeholder={t("home.eventConfig.wixEventIdPlaceholder")}
                    value={newEventWixId}
                    onChange={(e) => setNewEventWixId(e.target.value)}
                  />
                  <input
                    className="h-9 flex-1 rounded-md border border-border bg-background px-3 text-sm"
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
                </div>
              </div>
            </div>
          ) : null}

          {/* Unified event list */}
          {mergedEventRows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("home.integrations.noEvents")}</p>
          ) : (
            <div className="divide-y divide-border/60 rounded-xl border border-border/70">
              {mergedEventRows.map((row) => {
                const scope = row.binding ? scopeAudits[row.binding.binding_id] : null;
                return (
                  <div key={row.wixEventId} className="px-4 py-3 space-y-3">
                    {/* Event header */}
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="font-medium">{row.displayName}</div>
                        <div className="text-xs text-muted-foreground">{row.wixEventId}</div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {row.binding ? (
                          <Badge variant={row.binding.status === "verified" ? "default" : "secondary"}>
                            {row.binding.status}
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-muted-foreground">{t("home.integrations.noBinding")}</Badge>
                        )}
                        {!row.eventConfig ? (
                          <Badge variant="outline" className="text-muted-foreground">{t("home.integrations.noEventConfig")}</Badge>
                        ) : null}
                        {row.eventConfig ? (
                          <>
                            <Button
                              className="h-7 px-3 text-xs"
                              variant="outline"
                              onClick={() => setResetTargetEventId(resetTargetEventId === row.wixEventId ? null : row.wixEventId)}
                            >
                              {t("home.eventConfig.resetEventLabel")}
                            </Button>
                            <Button
                              className="h-7 border-red-400/50 px-3 text-xs text-red-600 hover:bg-red-500/10"
                              variant="outline"
                              onClick={() => setEventToDelete({ event_id: row.eventConfig!.event_id, name: row.eventConfig!.name })}
                            >
                              {t("home.eventConfig.deleteEvent")}
                            </Button>
                          </>
                        ) : null}
                      </div>
                    </div>

                    {/* Binding details */}
                    {row.binding ? (
                      <div className="rounded-lg border border-border/50 bg-muted/20 p-3 text-sm space-y-2">
                        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{t("home.bindings.title")}</div>
                        <div className="text-muted-foreground">
                          {(row.binding.wix_site_name && `${row.binding.wix_site_name} (${row.binding.wix_site_id})`) || row.binding.wix_site_id}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {t("home.bindings.app")}: {row.binding.app_installation_status}
                          {" · "}
                          {t("home.scopes.label")}: {scope ? scope.status : t("home.scopes.notChecked")}
                        </div>
                        {scope?.missing_scopes?.length ? (
                          <div className="text-xs text-amber-600">{t("home.scopes.missing")}: {scope.missing_scopes.join(", ")}</div>
                        ) : null}
                        {row.binding.last_verification_error ? (
                          <div className="text-xs text-red-500">{row.binding.last_verification_error}</div>
                        ) : null}
                        <div className="flex flex-wrap gap-2">
                          <Button className="h-7 px-3 text-xs" variant="outline" onClick={() => void handleVerifyBinding(row.binding!.binding_id)}>
                            {t("home.bindings.verify")}
                          </Button>
                          <Button
                            className="h-7 px-3 text-xs"
                            variant="outline"
                            onClick={() => void handleVerifyScopes(row.binding!.binding_id)}
                            disabled={row.binding.status !== "verified"}
                          >
                            {t("home.scopes.verify")}
                          </Button>
                          <Button
                            className="h-7 px-3 text-xs"
                            onClick={() => void handleActivateEvent(row.wixEventId)}
                            disabled={row.binding.status !== "verified"}
                          >
                            {t("home.bindings.activate")}
                          </Button>
                        </div>
                      </div>
                    ) : null}

                    {/* Reset confirm panel */}
                    {row.eventConfig && resetTargetEventId === row.wixEventId ? (
                      <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 space-y-2">
                        <div className="text-xs font-medium text-destructive">{t("home.eventConfig.resetConfirmTitle")}</div>
                        <p className="text-xs text-muted-foreground">{t("home.eventConfig.resetConfirmDescription")}</p>
                        <div className="flex flex-wrap gap-2">
                          <input className="h-8 flex-1 rounded border border-border bg-background px-2 text-xs" placeholder={t("home.eventConfig.resetReasonPlaceholder")} title={t("home.eventConfig.resetReasonLabel")} value={resetReason} onChange={(e) => setResetReason(e.target.value)} />
                          <input className="h-8 rounded border border-border bg-background px-2 text-xs" placeholder={t("home.eventConfig.resetActorPlaceholder")} title={t("home.eventConfig.resetActorLabel")} value={resetActor} onChange={(e) => setResetActor(e.target.value)} />
                          <input className="h-8 rounded border border-border bg-background px-2 text-xs" type="password" placeholder={t("home.eventConfig.resetAdminKeyPlaceholder")} title={t("home.eventConfig.resetAdminKeyLabel")} value={resetAdminKey} onChange={(e) => setResetAdminKey(e.target.value)} />
                          <Button className="h-8 border-red-500/40 px-3 text-xs text-red-600 hover:bg-red-500/10" variant="outline" disabled={resetInProgress || !resetReason.trim() || !resetActor.trim() || !resetAdminKey.trim()} onClick={() => void handleResetEvent(row.wixEventId)}>
                            {t("home.eventConfig.resetConfirmButton")}
                          </Button>
                          <Button className="h-8 px-3 text-xs" variant="ghost" onClick={() => setResetTargetEventId(null)}>
                            {t("home.eventConfig.resetCancelButton")}
                          </Button>
                        </div>
                      </div>
                    ) : null}

                    {/* Blocks — always visible */}
                    <div className="rounded-lg border border-border/50 bg-muted/20 p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="text-xs font-medium text-muted-foreground">{t("home.eventConfig.blocks")}</div>
                        {row.eventConfig ? (
                          <Button
                            className="h-6 px-2 text-xs"
                            variant="outline"
                            onClick={() => setSelectedEventForBlocks(selectedEventForBlocks === row.eventConfig!.event_id ? null : row.eventConfig!.event_id)}
                          >
                            {t("home.eventConfig.addBlock")} +
                          </Button>
                        ) : null}
                      </div>

                      {row.eventConfig && selectedEventForBlocks === row.eventConfig.event_id ? (
                        <BlockForm onSubmit={(data) => handleAddBlock(row.eventConfig!.event_id, data)} />
                      ) : null}

                      {loadingBlocksMap[row.eventConfig?.event_id ?? ""] ? (
                        <div className="text-xs text-muted-foreground">{t("home.eventConfig.loading")}</div>
                      ) : !row.eventConfig ? (
                        <div className="text-xs text-muted-foreground">{t("home.integrations.noEventConfig")}</div>
                      ) : (blocksMap[row.eventConfig.event_id] ?? []).length === 0 ? (
                        <div className="text-xs text-muted-foreground">{t("home.eventConfig.noBlocks")}</div>
                      ) : (
                        <div className="divide-y divide-border/40 rounded-lg border border-border/40">
                          {(blocksMap[row.eventConfig.event_id] ?? []).map((bl) => (
                            <div key={bl.block_id} className="flex items-center justify-between px-3 py-2 text-xs">
                              <div>
                                <span className="font-medium">{bl.name}</span>
                                <span className="ml-2 text-muted-foreground">[{bl.block_code}]</span>
                                <span className="ml-2 text-muted-foreground">{t("home.eventConfig.gracePeriodLabel")}: {bl.grace_period_minutes}m</span>
                                <span className="ml-2 text-muted-foreground">{t("home.eventConfig.priorityLabel")}: {bl.priority}</span>
                                <span className="ml-2 text-muted-foreground">{bl.starts_at} → {bl.ends_at}</span>
                              </div>
                              <Button className="h-6 border-red-400/50 px-2 text-xs text-red-600 hover:bg-red-500/10" variant="outline" onClick={() => void handleDeleteBlock(bl.block_id, row.eventConfig!.event_id)}>
                                {t("home.eventConfig.deleteBlock")}
                              </Button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Reset Audit Trail */}
          <div className="space-y-2 pt-2 border-t border-border/40">
            <div className="flex items-center gap-2">
              <div className="text-sm font-medium">{t("home.eventConfig.auditTrailLabel")}</div>
              <div className="flex gap-2">
                <input className="h-7 rounded border border-border bg-background px-2 text-xs" type="password" placeholder={t("home.eventConfig.resetAdminKeyPlaceholder")} title={t("home.eventConfig.resetAdminKeyLabel")} value={resetAdminKey} onChange={(e) => setResetAdminKey(e.target.value)} />
                <Button className="h-7 px-3 text-xs" variant="outline" onClick={() => void loadAuditTrail()}>{t("home.common.refresh")}</Button>
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
                      {" · "}<span className="text-muted-foreground">{rec.scope_id}</span>
                      {" · "}{rec.actor}{" — "}{rec.reason}
                      {" ("}<span className="font-medium">{rec.records_cleared}</span>{" cleared)"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Delete event confirm modal */}
      {eventToDelete ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="w-full max-w-sm rounded-2xl border border-border bg-background shadow-xl">
            <div className="px-5 py-4">
              <h3 className="text-base font-semibold">{t("home.deleteEventModal.title")}</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("home.deleteEventModal.body", { name: eventToDelete.name })}
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-border/70 px-5 py-3">
              <Button variant="secondary" onClick={() => setEventToDelete(null)}>
                {t("home.deleteEventModal.cancel")}
              </Button>
              <Button
                className="border-red-400/50 text-red-600 hover:bg-red-500/10"
                variant="outline"
                onClick={() => { void handleDeleteEvent(eventToDelete.event_id); setEventToDelete(null); }}
              >
                {t("home.deleteEventModal.confirm")}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Autobind selection modal */}
      {isAutobindModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="flex max-h-[80vh] w-full max-w-xl flex-col rounded-2xl border border-border bg-background shadow-xl">
            <div className="flex items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold">{t("home.autobindModal.title")}</h3>
                <p className="text-sm text-muted-foreground">{t("home.autobindModal.description")}</p>
              </div>
              <Button className="h-8 px-3 text-xs" variant="ghost" onClick={() => setIsAutobindModalOpen(false)}>
                {t("home.autobindModal.cancel")}
              </Button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              {loadingAutobindModal ? (
                <div className="py-8 text-center text-sm text-muted-foreground">{t("home.autobindModal.loading")}</div>
              ) : wixEventPreviewList.length === 0 ? (
                <div className="py-8 text-center text-sm text-muted-foreground">{t("home.autobindModal.noEvents")}</div>
              ) : (
                <div className="space-y-2">
                  {wixEventPreviewList.map((event) => {
                    const alreadyBound = bindings.some((b) => b.wix_event_id === event.wix_event_id);
                    const checked = selectedAutobindEventIds.has(event.wix_event_id);
                    return (
                      <label
                        key={event.wix_event_id}
                        className="flex cursor-pointer items-center gap-3 rounded-lg border border-border/70 bg-muted/20 px-4 py-3 hover:bg-muted/40"
                      >
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded accent-primary"
                          checked={checked}
                          disabled={alreadyBound}
                          onChange={() => {
                            setSelectedAutobindEventIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(event.wix_event_id)) {
                                next.delete(event.wix_event_id);
                              } else {
                                next.add(event.wix_event_id);
                              }
                              return next;
                            });
                          }}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium">{event.name}</div>
                          <div className="truncate text-xs text-muted-foreground">{event.wix_event_id}</div>
                        </div>
                        {alreadyBound ? (
                          <Badge variant="outline" className="shrink-0 text-xs text-green-600 border-green-400">
                            {t("home.autobindModal.alreadyBound")}
                          </Badge>
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-border/70 px-5 py-4">
              <span className="text-xs text-muted-foreground">
                {t("home.autobindModal.selected", { count: selectedAutobindEventIds.size })}
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setIsAutobindModalOpen(false)}>
                  {t("home.autobindModal.cancel")}
                </Button>
                <Button onClick={() => void handleConfirmAutobindModal()} disabled={selectedAutobindEventIds.size === 0}>
                  {t("home.autobindModal.confirm")}
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Binding help modal */}
      {bindingHelp.isOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-border bg-background shadow-xl">
            <div className="flex items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
              <div>
                <h3 className="text-lg font-semibold">{t("home.bindingHelp.title")}</h3>
                <p className="text-sm text-muted-foreground">{t("home.bindingHelp.subtitle")}</p>
              </div>
              <Button className="h-8 px-3 text-xs" variant="ghost" onClick={bindingHelp.close}>
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
                    <a className="underline" href="https://dev.wix.com/docs/api-reference/business-management/app-installation/skills/list-installed-apps" target="_blank" rel="noreferrer">
                      {t("home.bindingHelp.referenceApps")}
                    </a>
                  </li>
                  <li>
                    <a className="underline" href="https://dev.wix.com/docs/api-reference/business-solutions/events/skills/list-events" target="_blank" rel="noreferrer">
                      {t("home.bindingHelp.referenceEvents")}
                    </a>
                  </li>
                  <li>
                    <a className="underline" href="https://dev.wix.com/docs/api-reference/app-management/app-instance/get-app-instance" target="_blank" rel="noreferrer">
                      {t("home.bindingHelp.referenceInstance")}
                    </a>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
