import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  activateEvent,
  createSiteEventBinding,
  fetchWebhookHistory,
  listLatestScopeAudits,
  listSiteEventBindings,
  listVerifiedEvents,
  retryWebhookDelivery,
  verifyBindingScopes,
  verifySiteEventBinding,
  type SiteEventBindingRecord,
  type VerifiedEventRecord,
  type WixScopeAuditRecord,
  type WebhookDeliveryRecord,
} from "@/services/scannerApi";

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

  const loadWebhookHistory = async () => {
    setLoadingWebhooks(true);
    try {
      const rows = await fetchWebhookHistory(12);
      setWebhookHistory(rows);
    } catch {
      toast.error(t("home.webhook.loadError"));
    } finally {
      setLoadingWebhooks(false);
    }
  };

  useEffect(() => {
    void loadWebhookHistory();
  }, []);

  const loadBindings = async () => {
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
  };

  useEffect(() => {
    void loadBindings();
  }, []);

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

  return (
    <section className="grid gap-4 md:grid-cols-2">
      <Card className="border-border/70">
        <CardHeader>
          <Badge className="w-fit" variant="secondary">
            {t("nav.home")}
          </Badge>
          <CardTitle>{t("home.title")}</CardTitle>
          <CardDescription>{t("home.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center gap-3">
          <Button onClick={() => toast(t("toasts.welcome"))}>{t("home.toastButton")}</Button>
          <span className="text-sm text-muted-foreground">i18n default: es</span>
        </CardContent>
      </Card>

      <Card className="border-border/70 bg-muted/30">
        <CardHeader>
          <CardTitle>{t("home.devSurface.title")}</CardTitle>
          <CardDescription>{t("home.devSurface.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2 text-sm text-muted-foreground">
          <Badge variant="outline">/api/health</Badge>
          <Badge variant="outline">Toaster</Badge>
          <Badge variant="outline">Route placeholders</Badge>
        </CardContent>
      </Card>

      <Card className="border-border/70 md:col-span-2">
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
                  <Button size="sm" variant="outline" onClick={() => void handleRetry(item.id)}>
                    {t("home.webhook.retry")}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/70 md:col-span-2">
        <CardHeader>
          <CardTitle>{t("home.bindings.title")}</CardTitle>
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
                      <Button size="sm" variant="outline" onClick={() => void handleVerifyBinding(binding.binding_id)}>
                        {t("home.bindings.verify")}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void handleVerifyScopes(binding.binding_id)}
                        disabled={binding.status !== "verified"}
                      >
                        {t("home.scopes.verify")}
                      </Button>
                      <Button
                        size="sm"
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
    </section>
  );
}
