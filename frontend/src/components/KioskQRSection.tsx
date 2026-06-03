import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { QRCodeCanvas } from "qrcode.react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  createKiosk,
  KioskRecord,
  listKiosks,
  listVerifiedEvents,
  regenerateKioskQR,
  setKioskQRActive,
  type VerifiedEventRecord,
} from "../services/scannerApi";

function buildPayload(kioskId: string, token: string) {
  // compact JSON payload -> base64, prefixed
  try {
    const raw = JSON.stringify({ k: kioskId, t: token });
    const b = typeof window !== "undefined" && typeof window.btoa === "function" ? window.btoa(raw) : raw;
    return `KIOSK:v1:${b}`;
  } catch (e) {
    return `KIOSK:v1:${token}`;
  }
}

export default function KioskQRSection(): JSX.Element {
  const { t } = useTranslation();
  const [kiosks, setKiosks] = useState<KioskRecord[]>([]);
  const [verifiedEvents, setVerifiedEvents] = useState<VerifiedEventRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [selected, setSelected] = useState<{ kiosk: KioskRecord; token: string } | null>(null);
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  // Admin API key is provided from environment in dev; do not expose edit in UI.
  const adminApiKey = import.meta.env.VITE_ADMIN_API_KEY ?? "";
  const [form, setForm] = useState({
    event_id: "",
    station_id: "",
    actor: "operator-ui",
    mode: "reusable_with_expiry" as "one_time" | "reusable_with_expiry",
    expires_minutes: 60,
  });

  const eventOptions = useMemo(
    () =>
      verifiedEvents.map((event) => ({
        value: event.wix_event_id,
        label: event.wix_event_name ? `${event.wix_event_name} (${event.wix_event_id})` : event.wix_event_id,
        siteId: event.wix_site_id,
      })),
    [verifiedEvents],
  );

  const load = async () => {
    if (!adminApiKey.trim()) {
      setKiosks([]);
      return;
    }
    setLoading(true);
    try {
      const rows = await listKiosks(adminApiKey.trim());
      setKiosks(rows);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.kiosks.loadError", "Failed to load kiosks"));
    } finally {
      setLoading(false);
    }
  };

  const loadVerified = async () => {
    setLoadingEvents(true);
    try {
      const rows = await listVerifiedEvents();
      setVerifiedEvents(rows);
      setForm((current) =>
        current.event_id || rows.length === 0
          ? current
          : { ...current, event_id: rows[0].wix_event_id },
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.kiosks.loadEventsError", "Failed to load verified events"));
    } finally {
      setLoadingEvents(false);
    }
  };

  useEffect(() => {
    void loadVerified();
  }, []);

  useEffect(() => {
    void load();
  }, []);

  const selectedEvent = eventOptions.find((option) => option.value === form.event_id) ?? null;

  const eventNameMap = useMemo(
    () => new Map(verifiedEvents.map((e) => [e.wix_event_id, e.wix_event_name ?? null])),
    [verifiedEvents],
  );

  const handleToggle = async (k: KioskRecord) => {
    if (!adminApiKey.trim()) {
      toast.error(t("home.kiosks.adminKeyRequired", "Enter the admin API key first"));
      return;
    }
    try {
      const updated = await setKioskQRActive(adminApiKey.trim(), k.kiosk_id, k.status !== "active");
      setKiosks((prev) => prev.map((p) => (p.kiosk_id === updated.kiosk_id ? updated : p)));
      toast.success(t("home.kiosks.updated", "Updated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.kiosks.updateError", "Failed to update kiosk"));
    }
  };

  const handleRegenerate = async (k: KioskRecord) => {
    if (!adminApiKey.trim()) {
      toast.error(t("home.kiosks.adminKeyRequired", "Enter the admin API key first"));
      return;
    }
    if (!confirm(t("kiosks.confirmRegenerate", "Regenerate QR for this kiosk?"))) return;
    setRegeneratingId(k.kiosk_id);
    try {
      const res = await regenerateKioskQR(adminApiKey.trim(), k.kiosk_id);
      // server returns token once
      setSelected({ kiosk: k, token: res.token });
      // refresh list to pick up preview/status
      await load();
      toast.success(t("kiosks.regenerated", "QR regenerated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.kiosks.regenerateError", "Failed to regenerate"));
    } finally {
      setRegeneratingId(null);
    }
  };

  const handleDownload = () => {
    if (!selected) return;
    const el = document.getElementById("kiosk-qr-canvas") as HTMLCanvasElement | null;
    if (!el) return toast.error("QR not available");
    const data = el.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = data;
    a.download = `kiosk-${selected.kiosk.kiosk_id}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const handlePrint = () => {
    if (!selected) return;
    const el = document.getElementById("kiosk-qr-canvas") as HTMLCanvasElement | null;
    if (!el) return toast.error("QR not available");
    const data = el.toDataURL("image/png");
    const w = window.open("", "_blank", "noopener,noreferrer");
    if (!w) return toast.error("Unable to open print window");
    w.document.write(`<html><head><title>Print QR</title></head><body style="display:flex;align-items:center;justify-content:center;height:100vh;margin:0;"><img src='${data}' style='max-width:100%;height:auto' /></body></html>`);
    w.document.close();
    w.focus();
    // give it a moment
    setTimeout(() => {
      w.print();
      w.close();
    }, 250);
  };

  return (
    <div className="space-y-4">
      <Card className="border-border/70 shadow-sm">
        <CardHeader className="space-y-2">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>{t("home.kiosks.title", "Gestion de Kioscos QR")}</CardTitle>
              <CardDescription>{t("home.kiosks.description", "Create and manage bootstrap QR codes for kiosk devices.")}</CardDescription>
            </div>
            <Button variant="outline" className="h-8 px-3 text-xs" onClick={() => void load()} disabled={loading || !adminApiKey.trim()}>
              {loading ? t("home.common.refreshing", "Refreshing...") : t("home.kiosks.refresh", "Refresh")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-1">
            

            <div className="rounded-2xl border border-border/70 bg-muted/20 p-4">
              <div className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">{t("home.kiosks.createTitle", "Create kiosk")}</div>
              <div className="space-y-3">
                <label className="space-y-1 text-sm">
                  <span className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.kiosks.eventLabel", "Verified event")}</span>
                  <select
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm outline-none transition focus:border-primary disabled:opacity-60"
                    value={form.event_id}
                    onChange={(e) => setForm((s) => ({ ...s, event_id: e.target.value }))}
                    disabled={loadingEvents || eventOptions.length === 0}
                  >
                    <option value="">{loadingEvents ? t("home.kiosks.loadingEvents", "Loading verified events...") : t("home.kiosks.eventPlaceholder", "Select a verified event")}</option>
                    {eventOptions.map((event) => (
                      <option key={event.value} value={event.value}>
                        {event.label} • {event.siteId}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground">{t("home.kiosks.eventHelp", "This list is sourced from verified bindings and the event id is stored in the bootstrap credential record.")}</p>
                </label>

                <div className="grid gap-3 md:grid-cols-2">
                  <label className="space-y-1 text-sm">
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.kiosks.stationLabel", "Station ID")}</span>
                    <input
                      className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm outline-none transition focus:border-primary"
                      type="text"
                      placeholder={t("home.kiosks.stationPlaceholder", "station-01")}
                      value={form.station_id}
                      onChange={(e) => setForm((s) => ({ ...s, station_id: e.target.value }))}
                    />
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.kiosks.actorLabel", "Actor")}</span>
                    <input
                      className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm outline-none transition focus:border-primary"
                      type="text"
                      placeholder={t("home.kiosks.actorPlaceholder", "operator-ui")}
                      value={form.actor}
                      onChange={(e) => setForm((s) => ({ ...s, actor: e.target.value }))}
                    />
                  </label>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <label className="space-y-1 text-sm">
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.kiosks.modeLabel", "QR mode")}</span>
                    <select
                      className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm outline-none transition focus:border-primary"
                      value={form.mode}
                      onChange={(e) => setForm((s) => ({ ...s, mode: e.target.value as typeof form.mode }))}
                    >
                      <option value="reusable_with_expiry">{t("home.kiosks.modeReusable", "Reusable with expiry")}</option>
                      <option value="one_time">{t("home.kiosks.modeOneTime", "One-time")}</option>
                    </select>
                  </label>
                  <label className="space-y-1 text-sm">
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.kiosks.expiresLabel", "Expires in minutes")}</span>
                    <input
                      className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm outline-none transition focus:border-primary"
                      type="number"
                      min={5}
                      max={1440}
                      value={form.expires_minutes}
                      onChange={(e) => setForm((s) => ({ ...s, expires_minutes: Number(e.target.value) }))}
                    />
                  </label>
                </div>

                <Button
                  className="w-full"
                  disabled={creating || !adminApiKey.trim() || !form.event_id || !form.station_id}
                  onClick={async () => {
                    if (!adminApiKey.trim()) return toast.error(t("home.kiosks.adminKeyRequired", "Enter the admin API key first"));
                    if (!form.event_id || !form.station_id) return toast.error(t("home.kiosks.formRequired", "Select an event and enter a station id"));
                    setCreating(true);
                    try {
                      const res = await createKiosk(adminApiKey.trim(), {
                        event_id: form.event_id,
                        station_id: form.station_id,
                        actor: form.actor,
                        mode: form.mode,
                        expires_minutes: form.expires_minutes,
                      });
                      toast.success(t("home.kiosks.createSuccess", "Kiosk created"));
                      const fake: KioskRecord = {
                        kiosk_id: res.kiosk_id,
                        name: selectedEvent?.label ?? null,
                        site_id: selectedEvent?.siteId ?? "",
                        event_id: form.event_id,
                        station_id: form.station_id,
                        status: "active",
                        token_preview: res.token_preview ?? null,
                        last_regenerated_at: res.created_at,
                        created_at: res.created_at,
                      };
                      setSelected({ kiosk: fake, token: res.token });
                      await load();
                    } catch (err) {
                      toast.error(err instanceof Error ? err.message : t("home.kiosks.createError", "Failed to create kiosk"));
                    } finally {
                      setCreating(false);
                    }
                  }}
                >
                  {creating ? t("home.common.refreshing", "Creating...") : t("home.kiosks.createButton", "Create kiosk")}
                </Button>
              </div>
            </div>
          </div>

          {!adminApiKey.trim() ? (
            <div className="rounded-xl border border-dashed border-border/70 bg-muted/30 p-4 text-sm text-muted-foreground">
              {t("home.kiosks.adminKeyHint", "Enter the admin API key above to load kiosks and manage bootstrap credentials.")}
            </div>
          ) : null}

          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">{t("home.kiosks.listTitle", "Existing kiosks")}</div>
                <div className="text-sm text-muted-foreground">{t("home.kiosks.listDescription", "These rows are backed by bootstrap credential records.")}</div>
              </div>
              {verifiedEvents.length > 0 ? <Badge variant="outline">{t("home.kiosks.verifiedCount", { defaultValue: "{{count}} verified events", count: verifiedEvents.length })}</Badge> : null}
            </div>

            {loading ? (
              <div className="rounded-xl border border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground">{t("home.kiosks.loading", "Loading kiosks...")}</div>
            ) : kiosks.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground">{t("home.kiosks.empty", "No kiosks found")}</div>
            ) : (
              <div className="space-y-3">
                {kiosks.map((k) => (
                  <div key={k.kiosk_id} className="rounded-2xl border border-border/70 bg-background p-4 shadow-sm">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="text-base font-semibold">{k.name ?? k.kiosk_id}</div>
                          <Badge variant={k.status === "active" ? "default" : "secondary"}>{t(`home.kiosks.status.${k.status}`, k.status)}</Badge>
                        </div>
                        <div className="grid gap-2 text-sm text-muted-foreground md:grid-cols-3">
                          <div>
                            <div className="text-xs uppercase tracking-wide">{t("home.kiosks.eventLabel", "Verified event")}</div>
                            <div className="font-medium text-foreground">{eventNameMap.get(k.event_id) ?? k.event_id}</div>
                          </div>
                          <div>
                            <div className="text-xs uppercase tracking-wide">{t("home.kiosks.stationLabel", "Station ID")}</div>
                            <div className="font-medium text-foreground">{k.station_id ?? "-"}</div>
                          </div>
                          <div>
                            <div className="text-xs uppercase tracking-wide">{t("home.kiosks.siteLabel", "Relay / site")}</div>
                            <div className="font-medium text-foreground">{k.site_id || t("home.kiosks.notAvailable", "Not available")}</div>
                          </div>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {k.last_regenerated_at ? `${t("home.kiosks.rotatedAt", "Rotated")}: ${k.last_regenerated_at}` : t("home.kiosks.notRotated", "Not rotated yet")}
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2">
                        <Button variant="outline" className="h-8 px-3 text-xs" onClick={() => void handleToggle(k)}>
                          {k.status === "active" ? t("home.kiosks.deactivate", "Deactivate") : t("home.kiosks.activate", "Activate")}
                        </Button>
                        <Button variant="outline" className="h-8 px-3 text-xs" onClick={() => void handleRegenerate(k)} disabled={regeneratingId === k.kiosk_id}>
                          {regeneratingId === k.kiosk_id ? t("home.kiosks.regenerating", "Regenerating...") : t("home.kiosks.regenerate", "Regenerate")}
                        </Button>
                        <Button variant="outline" className="h-8 px-3 text-xs" onClick={() => setSelected({ kiosk: k, token: k.token_preview ?? "" })}>
                          {t("home.kiosks.view", "View")}
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl">
            <div className="flex items-start justify-between">
              <div>
                <h4 className="text-lg font-medium">{selected.kiosk.name ?? selected.kiosk.kiosk_id}</h4>
                <div className="text-sm text-muted-foreground">{selected.kiosk.site_id || t("home.kiosks.notAvailable", "Not available")} • {eventNameMap.get(selected.kiosk.event_id) ?? selected.kiosk.event_id}</div>
              </div>
              <Button variant="ghost" className="h-8 px-3 text-xs" onClick={() => setSelected(null)}>{t("home.kiosks.close", "Close")}</Button>
            </div>

            <div className="mt-4 flex flex-col items-center gap-3">
              {selected.token.includes(".") ? (
                <>
                  <QRCodeCanvas id="kiosk-qr-canvas" value={buildPayload(selected.kiosk.kiosk_id, selected.token)} size={256} level="H" includeMargin={true} />
                  <div className="text-sm text-muted-foreground break-all">{t("home.kiosks.oneTimeNote", "This token is shown only once after regeneration. Copy or print it now.")}</div>
                  <div className="flex gap-2">
                    <Button variant="outline" className="h-8 px-3 text-xs" onClick={() => { navigator.clipboard?.writeText(selected.token); toast.success(t("home.kiosks.copied", "Copied")); }}>
                      {t("home.kiosks.copy", "Copy token")}
                    </Button>
                    <Button variant="outline" className="h-8 px-3 text-xs" onClick={handleDownload}>{t("home.kiosks.download", "Download PNG")}</Button>
                    <Button variant="outline" className="h-8 px-3 text-xs" onClick={handlePrint}>{t("home.kiosks.print", "Print")}</Button>
                  </div>
                </>
              ) : (
                <div className="rounded-xl border border-dashed border-border/70 bg-muted/30 p-6 text-center text-sm text-muted-foreground">
                  <div className="mb-1 font-medium text-foreground">{t("home.kiosks.tokenUnavailable", "Full token no longer available")}</div>
                  {t("home.kiosks.tokenUnavailableHint", "The token is shown only once when first generated. Use Regenerate to issue a new QR code.")}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
