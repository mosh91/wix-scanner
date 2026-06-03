import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useHelpModal } from "@/hooks/useHelpModal";
import {
  createBootstrapCredential,
  disableRelay,
  enableRelay,
  listBootstrapCredentials,
  listRelays,
  registerRelay,
  revokeBootstrapCredential,
  rotateRelayCredentials,
  type BootstrapCredentialRecord,
  type RelayInstanceRecord,
} from "@/services/scannerApi";

export default function RelayManagementTab() {
  const { t } = useTranslation();
  const help = useHelpModal();

  const [relayAdminKey, setRelayAdminKey] = useState("");
  const [relays, setRelays] = useState<RelayInstanceRecord[]>([]);
  const [relayLoading, setRelayLoading] = useState(false);
  const [relayError, setRelayError] = useState<string | null>(null);
  // Register form
  const [regRelayName, setRegRelayName] = useState("");
  const [regVenue, setRegVenue] = useState("");
  const [regStationId, setRegStationId] = useState("");
  const [regNotes, setRegNotes] = useState("");
  const [regToken, setRegToken] = useState<string | null>(null);
  const [regInProgress, setRegInProgress] = useState(false);
  // Rotate relay creds
  const [rotRelayId, setRotRelayId] = useState("");
  const [rotGrace] = useState(15);
  const [rotToken, setRotToken] = useState<string | null>(null);
  const [rotGraceExpires, setRotGraceExpires] = useState<string | null>(null);
  const [rotInProgress, setRotInProgress] = useState(false);
  // Bootstrap credentials
  const [bootstrapCreds, setBootstrapCreds] = useState<BootstrapCredentialRecord[]>([]);
  const [bsEventId, setBsEventId] = useState("");
  const [bsStationId, setBsStationId] = useState("");
  const [bsDoorId, setBsDoorId] = useState("");
  const [bsActor, setBsActor] = useState("admin");
  const [bsMode, setBsMode] = useState<"one_time" | "reusable_with_expiry">("one_time");
  const [bsExpiry, setBsExpiry] = useState(60);
  const [bsRelayId, setBsRelayId] = useState("");
  const [bsGenerating, setBsGenerating] = useState(false);
  const [bsLastToken, setBsLastToken] = useState<string | null>(null);
  const [bsLastUrl, setBsLastUrl] = useState<string | null>(null);
  const [bsCopied, setBsCopied] = useState(false);

  return (
    <>
      <Card className="border-border/70">
        <CardHeader className="flex flex-row items-start justify-between gap-2">
          <div>
            <CardTitle>{t("home.relayManagement.title")}</CardTitle>
            <CardDescription>{t("home.relayManagement.description")}</CardDescription>
          </div>
          <Button
            variant="ghost"
            className="h-8 w-8 shrink-0 text-muted-foreground"
            onClick={help.open}
            title={t("home.relayManagement.helpTitle")}
          >
            ?
          </Button>
        </CardHeader>
        <CardContent className="space-y-8">
          {/* Admin key gate */}
          <div className="space-y-1">
            <label className="text-sm font-medium">{t("home.relayManagement.adminKeyLabel")}</label>
            <div className="flex gap-2">
              <input
                type="password"
                className="h-9 flex-1 rounded-lg border border-border bg-background px-3 text-sm"
                placeholder={t("home.relayManagement.adminKeyPlaceholder")}
                value={relayAdminKey}
                onChange={(e) => setRelayAdminKey(e.target.value)}
              />
              <Button
                className="h-9 px-3 text-xs"
                disabled={!relayAdminKey || relayLoading}
                onClick={async () => {
                  setRelayLoading(true);
                  setRelayError(null);
                  try {
                    const [r, b] = await Promise.all([
                      listRelays(relayAdminKey),
                      listBootstrapCredentials(relayAdminKey),
                    ]);
                    setRelays(r);
                    setBootstrapCreds(b);
                  } catch {
                    setRelayError(t("home.relayManagement.loadError"));
                  } finally {
                    setRelayLoading(false);
                  }
                }}
              >
                {relayLoading ? "…" : t("home.relayManagement.load")}
              </Button>
            </div>
            {relayError && <p className="text-sm text-destructive">{relayError}</p>}
          </div>

          {!relayAdminKey ? (
            <p className="text-sm text-muted-foreground">{t("home.relayManagement.accessDenied")}</p>
          ) : (
            <>
              {/* ---------- Relay list ---------- */}
              <section className="space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{t("home.relayManagement.relayListTitle")}</h3>
                  <Button
                    variant="outline"
                    className="h-8 px-3 text-xs"
                    disabled={relayLoading}
                    onClick={async () => {
                      setRelayLoading(true);
                      try {
                        const r = await listRelays(relayAdminKey);
                        setRelays(r);
                      } catch {
                        setRelayError(t("home.relayManagement.loadError"));
                      } finally {
                        setRelayLoading(false);
                      }
                    }}
                  >
                    {t("home.relayManagement.refresh")}
                  </Button>
                </div>
                {relays.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("home.relayManagement.emptyRelays")}</p>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-border">
                    <table className="w-full text-xs">
                      <thead className="bg-muted/40">
                        <tr>
                          {["colName", "colVenue", "colStation", "colStatus", "colHeartbeat", "colQueueDepth", "colVersion", "colCredentials", ""].map((k) => (
                            <th key={k} className="px-3 py-2 text-left font-medium text-muted-foreground">
                              {k ? t(`home.relayManagement.${k}`) : ""}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {relays.map((r) => (
                          <tr key={r.relay_id} className="border-t border-border">
                            <td className="px-3 py-2 font-medium">{r.relay_name}</td>
                            <td className="px-3 py-2">{r.venue}</td>
                            <td className="px-3 py-2 font-mono">{r.station_id}</td>
                            <td className="px-3 py-2">
                              <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${r.status === "active" ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300" : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"}`}>
                                {r.status === "active" ? t("home.relayManagement.statusActive") : t("home.relayManagement.statusDisabled")}
                              </span>
                              {r.heartbeat_stale && (
                                <span className="ml-1 inline-flex rounded px-1.5 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300">
                                  {t("home.relayManagement.statusStale")}
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-muted-foreground">
                              {r.last_heartbeat ? new Date(r.last_heartbeat).toLocaleString() : "—"}
                            </td>
                            <td className="px-3 py-2">{r.queue_depth}</td>
                            <td className="px-3 py-2 text-muted-foreground">{r.software_version ?? "—"}</td>
                            <td className="px-3 py-2 font-mono text-muted-foreground">{r.auth_token_preview ?? "—"}</td>
                            <td className="px-3 py-2">
                              <div className="flex gap-1">
                                {r.status === "disabled" ? (
                                  <Button variant="outline" className="h-6 px-2 text-xs"
                                    onClick={async () => {
                                      try {
                                        const updated = await enableRelay(relayAdminKey, r.relay_id);
                                        setRelays((prev) => prev.map((x) => x.relay_id === r.relay_id ? updated : x));
                                        toast.success(t("home.relayManagement.statusActive"));
                                      } catch { toast.error(t("home.relayManagement.loadError")); }
                                    }}
                                  >{t("home.relayManagement.enableButton")}</Button>
                                ) : (
                                  <Button variant="outline" className="h-6 px-2 text-xs"
                                    onClick={async () => {
                                      try {
                                        const updated = await disableRelay(relayAdminKey, r.relay_id);
                                        setRelays((prev) => prev.map((x) => x.relay_id === r.relay_id ? updated : x));
                                        toast.success(t("home.relayManagement.statusDisabled"));
                                      } catch { toast.error(t("home.relayManagement.loadError")); }
                                    }}
                                  >{t("home.relayManagement.disableButton")}</Button>
                                )}
                                <Button variant="outline" className="h-6 px-2 text-xs"
                                  disabled={rotInProgress && rotRelayId === r.relay_id}
                                  onClick={async () => {
                                    setRotRelayId(r.relay_id);
                                    setRotInProgress(true);
                                    try {
                                      const res = await rotateRelayCredentials(relayAdminKey, r.relay_id, rotGrace);
                                      setRotToken(res.new_auth_token);
                                      setRotGraceExpires(res.grace_expires_at);
                                      const updated = await listRelays(relayAdminKey);
                                      setRelays(updated);
                                      toast.success(t("home.relayManagement.rotateCredsSuccess"));
                                    } catch { toast.error(t("home.relayManagement.rotateCredsError")); }
                                    finally { setRotInProgress(false); }
                                  }}
                                >{t("home.relayManagement.rotateCredsButton")}</Button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Rotated token display */}
                {rotToken && (
                  <div className="rounded-lg border border-yellow-300 bg-yellow-50 p-3 dark:bg-yellow-900/20">
                    <p className="text-xs font-medium text-yellow-800 dark:text-yellow-300">{t("home.relayManagement.rotatedTokenLabel")}</p>
                    <p className="mt-1 break-all font-mono text-xs">{rotToken}</p>
                    {rotGraceExpires && (
                      <p className="mt-1 text-xs text-muted-foreground">{t("home.relayManagement.rotateCredsGrace")}: {new Date(rotGraceExpires).toLocaleString()}</p>
                    )}
                  </div>
                )}
              </section>

              {/* ---------- Register relay form ---------- */}
              <section className="space-y-3">
                <h3 className="text-sm font-semibold">{t("home.relayManagement.registerTitle")}</h3>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <input
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.registerRelayNamePlaceholder")}
                    value={regRelayName}
                    onChange={(e) => setRegRelayName(e.target.value)}
                  />
                  <input
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.registerVenuePlaceholder")}
                    value={regVenue}
                    onChange={(e) => setRegVenue(e.target.value)}
                  />
                  <input
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.registerStationPlaceholder")}
                    value={regStationId}
                    onChange={(e) => setRegStationId(e.target.value)}
                  />
                  <input
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.registerNotes")}
                    value={regNotes}
                    onChange={(e) => setRegNotes(e.target.value)}
                  />
                </div>
                <Button
                  className="h-9 px-4 text-sm"
                  disabled={!regRelayName || !regVenue || !regStationId || regInProgress}
                  onClick={async () => {
                    setRegInProgress(true);
                    setRegToken(null);
                    try {
                      const res = await registerRelay(relayAdminKey, {
                        relay_name: regRelayName,
                        venue: regVenue,
                        station_id: regStationId,
                        notes: regNotes || undefined,
                      });
                      setRegToken(res.auth_token);
                      setRelays((prev) => [...prev, res]);
                      setRegRelayName(""); setRegVenue(""); setRegStationId(""); setRegNotes("");
                      toast.success(t("home.relayManagement.registerSuccess"));
                    } catch { toast.error(t("home.relayManagement.registerError")); }
                    finally { setRegInProgress(false); }
                  }}
                >
                  {regInProgress ? "…" : t("home.relayManagement.registerButton")}
                </Button>
                {regToken && (
                  <div className="rounded-lg border border-yellow-300 bg-yellow-50 p-3 dark:bg-yellow-900/20">
                    <p className="text-xs font-medium text-yellow-800 dark:text-yellow-300">{t("home.relayManagement.registerTokenLabel")}</p>
                    <p className="mt-1 break-all font-mono text-xs">{regToken}</p>
                  </div>
                )}
              </section>

              {/* ---------- Bootstrap credential generator ---------- */}
              <section className="space-y-3">
                <h3 className="text-sm font-semibold">{t("home.relayManagement.bootstrapTitle")}</h3>
                <p className="text-xs text-muted-foreground">{t("home.relayManagement.bootstrapDescription")}</p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3">
                  <input
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.bootstrapEventIdPlaceholder")}
                    value={bsEventId}
                    onChange={(e) => setBsEventId(e.target.value)}
                  />
                  <input
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.bootstrapStationIdPlaceholder")}
                    value={bsStationId}
                    onChange={(e) => setBsStationId(e.target.value)}
                  />
                  <input
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.bootstrapDoorIdPlaceholder")}
                    value={bsDoorId}
                    onChange={(e) => setBsDoorId(e.target.value)}
                  />
                  <input
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.bootstrapActorPlaceholder")}
                    value={bsActor}
                    onChange={(e) => setBsActor(e.target.value)}
                  />
                  <select
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    value={bsMode}
                    onChange={(e) => setBsMode(e.target.value as "one_time" | "reusable_with_expiry")}
                  >
                    <option value="one_time">{t("home.relayManagement.bootstrapModeOneTime")}</option>
                    <option value="reusable_with_expiry">{t("home.relayManagement.bootstrapModeReusable")}</option>
                  </select>
                  <input
                    type="number"
                    min={5}
                    max={1440}
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.bootstrapExpiry")}
                    value={bsExpiry}
                    onChange={(e) => setBsExpiry(Number(e.target.value))}
                  />
                  <input
                    className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.relayManagement.bootstrapRelayId")}
                    value={bsRelayId}
                    onChange={(e) => setBsRelayId(e.target.value)}
                  />
                </div>
                <Button
                  className="h-9 px-4 text-sm"
                  disabled={!bsEventId || !bsStationId || !bsActor || bsGenerating}
                  onClick={async () => {
                    setBsGenerating(true);
                    setBsLastToken(null);
                    setBsLastUrl(null);
                    setBsCopied(false);
                    try {
                      const res = await createBootstrapCredential(relayAdminKey, {
                        event_id: bsEventId,
                        station_id: bsStationId,
                        door_id: bsDoorId || undefined,
                        actor: bsActor,
                        mode: bsMode,
                        expires_minutes: bsExpiry,
                        relay_id: bsRelayId || undefined,
                      });
                      setBsLastToken(res.signed_token);
                      setBsLastUrl(res.bootstrap_url);
                      setBootstrapCreds((prev) => [res, ...prev]);
                      toast.success(t("home.relayManagement.bootstrapSuccess"));
                    } catch { toast.error(t("home.relayManagement.bootstrapError")); }
                    finally { setBsGenerating(false); }
                  }}
                >
                  {bsGenerating ? "…" : t("home.relayManagement.bootstrapGenerateButton")}
                </Button>

                {bsLastToken && bsLastUrl && (
                  <div className="space-y-3 rounded-lg border border-border p-4">
                    <div className="space-y-1">
                      <p className="text-xs font-medium">{t("home.relayManagement.bootstrapTokenLabel")}</p>
                      <p className="break-all font-mono text-xs">{bsLastToken}</p>
                      <Button
                        variant="outline"
                        className="h-7 px-3 text-xs"
                        onClick={() => {
                          navigator.clipboard.writeText(bsLastToken!);
                          setBsCopied(true);
                          setTimeout(() => setBsCopied(false), 2000);
                        }}
                      >
                        {bsCopied ? t("home.relayManagement.bootstrapCopied") : t("home.relayManagement.bootstrapCopy")}
                      </Button>
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs font-medium">{t("home.relayManagement.bootstrapQrLabel")}</p>
                      <img
                        src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(bsLastUrl)}`}
                        alt="Bootstrap QR code"
                        className="rounded border border-border"
                        width={200}
                        height={200}
                      />
                    </div>
                  </div>
                )}
              </section>

              {/* ---------- Bootstrap credential list ---------- */}
              <section className="space-y-2">
                <h3 className="text-sm font-semibold">{t("home.relayManagement.bootstrapListTitle")}</h3>
                {bootstrapCreds.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("home.relayManagement.bootstrapEmpty")}</p>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-border">
                    <table className="w-full text-xs">
                      <thead className="bg-muted/40">
                        <tr>
                          {["bootstrapColEvent", "bootstrapColStation", "bootstrapColMode", "bootstrapColExpiry", "bootstrapColStatus", "bootstrapColPreview", ""].map((k) => (
                            <th key={k} className="px-3 py-2 text-left font-medium text-muted-foreground">
                              {k ? t(`home.relayManagement.${k}`) : ""}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {bootstrapCreds.map((bc) => {
                          const isRevoked = !!bc.revoked_at;
                          const isUsed = !!bc.used_at;
                          const statusLabel = isRevoked
                            ? t("home.relayManagement.bootstrapStatusRevoked")
                            : isUsed
                            ? t("home.relayManagement.bootstrapStatusUsed")
                            : t("home.relayManagement.bootstrapStatusActive");
                          return (
                            <tr key={bc.credential_id} className="border-t border-border">
                              <td className="px-3 py-2 font-mono">{bc.event_id}</td>
                              <td className="px-3 py-2 font-mono">{bc.station_id}</td>
                              <td className="px-3 py-2">{bc.mode === "one_time" ? t("home.relayManagement.bootstrapModeOneTime") : t("home.relayManagement.bootstrapModeReusable")}</td>
                              <td className="px-3 py-2 text-muted-foreground">{new Date(bc.expires_at).toLocaleString()}</td>
                              <td className="px-3 py-2">
                                <span className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${isRevoked || isUsed ? "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400" : "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"}`}>
                                  {statusLabel}
                                </span>
                              </td>
                              <td className="px-3 py-2 font-mono">{bc.token_preview}</td>
                              <td className="px-3 py-2">
                                {!isRevoked && !isUsed && (
                                  <Button
                                    variant="outline"
                                    className="h-6 px-2 text-xs"
                                    onClick={async () => {
                                      try {
                                        const updated = await revokeBootstrapCredential(relayAdminKey, bc.credential_id, bsActor || "admin");
                                        setBootstrapCreds((prev) => prev.map((x) => x.credential_id === bc.credential_id ? updated : x));
                                        toast.success(t("home.relayManagement.revokeSuccess"));
                                      } catch { toast.error(t("home.relayManagement.revokeError")); }
                                    }}
                                  >
                                    {t("home.relayManagement.revokeButton")}
                                  </Button>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </CardContent>
      </Card>

      {/* Relay management help modal */}
      {help.isOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={help.close}
        >
          <div
            className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="mb-3 text-lg font-semibold">{t("home.relayManagement.helpTitle")}</h2>
            <p className="text-sm text-muted-foreground">{t("home.relayManagement.helpBody")}</p>
            <Button className="mt-4 h-9 w-full" onClick={help.close}>
              {t("home.relayManagement.helpClose")}
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
