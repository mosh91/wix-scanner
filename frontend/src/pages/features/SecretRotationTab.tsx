import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  listCredentialAuditLog,
  rotateCredential,
  type AuthMode,
  type CredentialAuditFilters,
  type CredentialLifecycleEvent,
} from "@/services/scannerApi";

export default function SecretRotationTab() {
  const { t } = useTranslation();

  const [credAuditAdminKey, setCredAuditAdminKey] = useState("");
  const [credAuditLog, setCredAuditLog] = useState<CredentialLifecycleEvent[]>([]);
  const [credAuditLoading, setCredAuditLoading] = useState(false);
  const [credAuditError, setCredAuditError] = useState<string | null>(null);
  const [credAuditFilterDateFrom, setCredAuditFilterDateFrom] = useState("");
  const [credAuditFilterDateTo, setCredAuditFilterDateTo] = useState("");
  const [credAuditFilterActor, setCredAuditFilterActor] = useState("");
  const [credAuditFilterAction, setCredAuditFilterAction] = useState("");
  const [credRotateId, setCredRotateId] = useState("");
  const [credRotateNewProfile, setCredRotateNewProfile] = useState("");
  const [credRotateNewAuthMode, setCredRotateNewAuthMode] = useState<AuthMode>("api_key");
  const [credRotateConfirmed, setCredRotateConfirmed] = useState(false);
  const [credRotateInProgress, setCredRotateInProgress] = useState(false);

  const loadAuditLog = async () => {
    setCredAuditLoading(true);
    setCredAuditError(null);
    try {
      const filters: CredentialAuditFilters = {
        dateFrom: credAuditFilterDateFrom || undefined,
        dateTo: credAuditFilterDateTo || undefined,
        actor: credAuditFilterActor || undefined,
        action: credAuditFilterAction || undefined,
      };
      const rows = await listCredentialAuditLog(credAuditAdminKey, filters);
      setCredAuditLog(rows);
    } catch {
      setCredAuditError(t("home.secretAudit.loadError"));
    } finally {
      setCredAuditLoading(false);
    }
  };

  return (
    <Card className="border-border/70">
      <CardHeader>
        <CardTitle>{t("home.secretAudit.title")}</CardTitle>
        <CardDescription>{t("home.secretAudit.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Admin key gate */}
        <div className="space-y-1">
          <label className="text-sm font-medium">{t("home.secretAudit.adminKeyLabel")}</label>
          <div className="flex gap-2">
            <input
              type="password"
              className="h-9 flex-1 rounded-lg border border-border bg-background px-3 text-sm"
              placeholder={t("home.secretAudit.adminKeyPlaceholder")}
              value={credAuditAdminKey}
              onChange={(e) => setCredAuditAdminKey(e.target.value)}
            />
            <Button className="h-9 px-3 text-xs" disabled={!credAuditAdminKey || credAuditLoading} onClick={() => void loadAuditLog()}>
              {credAuditLoading ? "…" : t("home.secretAudit.load")}
            </Button>
          </div>
        </div>

        {!credAuditAdminKey ? (
          <p className="text-sm text-muted-foreground">{t("home.secretAudit.accessDenied")}</p>
        ) : (
          <>
            {/* Filters */}
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <input
                className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                placeholder={t("home.secretAudit.filterDateFrom")}
                value={credAuditFilterDateFrom}
                onChange={(e) => setCredAuditFilterDateFrom(e.target.value)}
              />
              <input
                className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                placeholder={t("home.secretAudit.filterDateTo")}
                value={credAuditFilterDateTo}
                onChange={(e) => setCredAuditFilterDateTo(e.target.value)}
              />
              <input
                className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                placeholder={t("home.secretAudit.filterActor")}
                value={credAuditFilterActor}
                onChange={(e) => setCredAuditFilterActor(e.target.value)}
              />
              <input
                className="h-9 rounded-lg border border-border bg-background px-3 text-sm"
                placeholder={t("home.secretAudit.filterActionPlaceholder")}
                value={credAuditFilterAction}
                onChange={(e) => setCredAuditFilterAction(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <Button className="h-8 px-3 text-xs" variant="outline" disabled={credAuditLoading} onClick={() => void loadAuditLog()}>
                {t("home.secretAudit.applyFilters")}
              </Button>
              <Button
                className="h-8 px-3 text-xs"
                variant="ghost"
                onClick={() => {
                  setCredAuditFilterDateFrom("");
                  setCredAuditFilterDateTo("");
                  setCredAuditFilterActor("");
                  setCredAuditFilterAction("");
                }}
              >
                {t("home.secretAudit.clearFilters")}
              </Button>
            </div>

            {credAuditError ? <p className="text-sm text-destructive">{credAuditError}</p> : null}

            {/* Audit log table */}
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    <th className="px-3 py-2 text-left font-medium">{t("home.secretAudit.colTimestamp")}</th>
                    <th className="px-3 py-2 text-left font-medium">{t("home.secretAudit.colCredential")}</th>
                    <th className="px-3 py-2 text-left font-medium">{t("home.secretAudit.colActor")}</th>
                    <th className="px-3 py-2 text-left font-medium">{t("home.secretAudit.colAction")}</th>
                    <th className="px-3 py-2 text-left font-medium">{t("home.secretAudit.colNote")}</th>
                  </tr>
                </thead>
                <tbody>
                  {credAuditLog.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-3 py-4 text-center text-muted-foreground">
                        {t("home.secretAudit.empty")}
                      </td>
                    </tr>
                  ) : (
                    credAuditLog.map((ev) => (
                      <tr key={ev.event_id} className="border-b border-border/40 last:border-0">
                        <td className="px-3 py-2 font-mono">{ev.occurred_at}</td>
                        <td className="px-3 py-2 font-mono">{ev.credential_id}</td>
                        <td className="px-3 py-2">{ev.actor}</td>
                        <td className="px-3 py-2">
                          <span className="text-muted-foreground">{ev.from_state}</span>
                          {" → "}
                          <span className="font-medium">{ev.to_state}</span>
                        </td>
                        <td className="px-3 py-2">{ev.event_note ?? "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Rotate section */}
            <div className="space-y-3 rounded-lg border border-border/70 bg-muted/30 p-4">
              <div>
                <div className="font-medium text-sm">{t("home.secretAudit.rotateSection")}</div>
                <p className="text-xs text-muted-foreground mt-1">{t("home.secretAudit.rotateDescription")}</p>
              </div>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                <div className="space-y-1">
                  <label className="text-xs font-medium">{t("home.secretAudit.colCredential")}</label>
                  <input
                    className="h-9 w-full rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.secretAudit.rotateSelectPlaceholder")}
                    value={credRotateId}
                    onChange={(e) => setCredRotateId(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium">{t("home.secretAudit.rotateNewProfileLabel")}</label>
                  <input
                    className="h-9 w-full rounded-lg border border-border bg-background px-3 text-sm"
                    placeholder={t("home.secretAudit.rotateNewProfilePlaceholder")}
                    value={credRotateNewProfile}
                    onChange={(e) => setCredRotateNewProfile(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium">{t("home.secretAudit.rotateNewAuthModeLabel")}</label>
                  <select
                    className="h-9 w-full rounded-lg border border-border bg-background px-3 text-sm"
                    value={credRotateNewAuthMode}
                    onChange={(e) => setCredRotateNewAuthMode(e.target.value as AuthMode)}
                  >
                    <option value="api_key">api_key</option>
                    <option value="oauth">oauth</option>
                  </select>
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={credRotateConfirmed}
                  onChange={(e) => setCredRotateConfirmed(e.target.checked)}
                />
                {t("home.secretAudit.rotateConfirmLabel")}
              </label>
              <Button
                className="h-9 px-4 text-sm border-destructive text-destructive hover:bg-destructive/10"
                variant="outline"
                disabled={!credRotateId || !credRotateNewProfile || !credRotateConfirmed || credRotateInProgress}
                onClick={async () => {
                  setCredRotateInProgress(true);
                  try {
                    await rotateCredential(credRotateId, credRotateNewProfile, credRotateNewAuthMode);
                    toast.success(t("home.secretAudit.rotateSuccess"));
                    setCredRotateId("");
                    setCredRotateNewProfile("");
                    setCredRotateConfirmed(false);
                    const rows = await listCredentialAuditLog(credAuditAdminKey, {});
                    setCredAuditLog(rows);
                  } catch {
                    toast.error(t("home.secretAudit.rotateError"));
                  } finally {
                    setCredRotateInProgress(false);
                  }
                }}
              >
                {credRotateInProgress ? "…" : t("home.secretAudit.rotateButton")}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
