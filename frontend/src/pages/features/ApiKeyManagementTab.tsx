import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpModal } from "@/components/HelpModal";
import { useHelpModal } from "@/hooks/useHelpModal";
import { useAdminData } from "@/context/AdminDataContext";
import { saveApiKeySettings, testApiKeyConnection } from "@/services/scannerApi";

export default function ApiKeyManagementTab() {
  const { t } = useTranslation();
  const { apiKeySettings, setApiKeySettings, loadApiKeySettings, loadingApiKeySettings } = useAdminData();
  const help = useHelpModal();

  const [apiKeyValue, setApiKeyValue] = useState("");
  const [wixAccountId, setWixAccountId] = useState("");
  const [testingApiKey, setTestingApiKey] = useState(false);
  const [savingApiKey, setSavingApiKey] = useState(false);
  const [apiKeyTestResult, setApiKeyTestResult] = useState<{ ok: boolean; message: string; tested_at: string } | null>(null);

  // Keep the editable account id in sync with the saved settings.
  useEffect(() => {
    setWixAccountId(apiKeySettings?.wix_account_id ?? "");
  }, [apiKeySettings]);

  const handleTestApiKeyConnection = async () => {
    if (!apiKeyValue.trim()) {
      toast.error(t("home.apiKeySettings.apiKeyRequired"));
      return;
    }
    setTestingApiKey(true);
    try {
      const result = await testApiKeyConnection(apiKeyValue.trim(), wixAccountId.trim() || null, "operator-ui");
      setApiKeyTestResult(result);
      toast.success(t("home.apiKeySettings.testSuccess"));
    } catch (err) {
      const message = err instanceof Error ? err.message : t("home.apiKeySettings.testError");
      setApiKeyTestResult({ ok: false, message, tested_at: new Date().toISOString() });
      toast.error(message);
    } finally {
      setTestingApiKey(false);
    }
  };

  const handleSaveApiKeySettings = async () => {
    if (!apiKeyValue.trim()) {
      toast.error(t("home.apiKeySettings.apiKeyRequired"));
      return;
    }
    if (!wixAccountId.trim()) {
      toast.error(t("home.apiKeySettings.accountIdRequired"));
      return;
    }
    setSavingApiKey(true);
    try {
      const status = await saveApiKeySettings(apiKeyValue.trim(), wixAccountId.trim(), "operator-ui");
      setApiKeySettings(status);
      setApiKeyValue("");
      setApiKeyTestResult(null);
      toast.success(t("home.apiKeySettings.saveSuccess"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.apiKeySettings.saveError"));
    } finally {
      setSavingApiKey(false);
    }
  };

  return (
    <>
      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>{t("home.apiKeySettings.title")}</CardTitle>
              <CardDescription>{t("home.apiKeySettings.description")}</CardDescription>
            </div>
            <Button className="h-8 px-3 text-xs" variant="outline" onClick={help.open}>
              {t("home.apiKeySettings.helpButton")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.apiKeySettings.apiKeyLabel")}</span>
              <input
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                type="password"
                value={apiKeyValue}
                onChange={(event) => setApiKeyValue(event.target.value)}
                placeholder={t("home.apiKeySettings.apiKeyPlaceholder")}
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.apiKeySettings.accountIdLabel")}</span>
              <input
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                type="text"
                value={wixAccountId}
                onChange={(event) => setWixAccountId(event.target.value)}
                placeholder={t("home.apiKeySettings.accountIdPlaceholder")}
              />
            </label>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void handleTestApiKeyConnection()} disabled={testingApiKey || savingApiKey}>
              {testingApiKey ? t("home.common.refreshing") : t("home.apiKeySettings.testConnection")}
            </Button>
            <Button onClick={() => void handleSaveApiKeySettings()} disabled={savingApiKey}>
              {savingApiKey ? t("home.common.refreshing") : t("home.apiKeySettings.save")}
            </Button>
            <Button variant="outline" onClick={() => void loadApiKeySettings()} disabled={loadingApiKeySettings}>
              {loadingApiKeySettings ? t("home.common.refreshing") : t("home.common.refresh")}
            </Button>
          </div>

          {apiKeySettings ? (
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.apiKeySettings.status")}</div>
                <div className="mt-1 font-medium">{apiKeySettings.api_key_configured ? t("home.apiKeySettings.configured") : t("home.apiKeySettings.notConfigured")}</div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.apiKeySettings.accountId")}</div>
                <div className="mt-1 font-medium">{apiKeySettings.wix_account_id ?? t("home.apiKeySettings.notAvailable")}</div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.apiKeySettings.lastRotated")}</div>
                <div className="mt-1 font-medium">{apiKeySettings.last_rotated_at ?? t("home.apiKeySettings.notAvailable")}</div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.apiKeySettings.lastValidated")}</div>
                <div className="mt-1 font-medium">{apiKeySettings.last_validated_at ?? t("home.apiKeySettings.notAvailable")}</div>
              </div>
              <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm md:col-span-2">
                <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.apiKeySettings.lastValidationError")}</div>
                <div className="mt-1 font-medium">{apiKeySettings.last_validation_error ?? t("home.apiKeySettings.none")}</div>
              </div>
            </div>
          ) : null}

          {apiKeyTestResult ? (
            <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.apiKeySettings.lastTestResult")}</div>
              <div className="mt-1 font-medium">{apiKeyTestResult.ok ? t("home.apiKeySettings.testPassed") : t("home.apiKeySettings.testFailed")}</div>
              <div className="mt-1 text-muted-foreground">{apiKeyTestResult.message}</div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <HelpModal
        open={help.isOpen}
        onClose={help.close}
        title={t("home.apiKeySettings.helpModal.title")}
        subtitle={t("home.apiKeySettings.helpModal.subtitle")}
      >
        <div>
          <div className="font-medium">1. {t("home.apiKeySettings.helpModal.step1Title")}</div>
          <p className="text-muted-foreground">{t("home.apiKeySettings.helpModal.step1Body")}</p>
        </div>
        <div>
          <div className="font-medium">2. {t("home.apiKeySettings.helpModal.step2Title")}</div>
          <p className="text-muted-foreground">{t("home.apiKeySettings.helpModal.step2Body")}</p>
        </div>
        <div>
          <div className="font-medium">3. {t("home.apiKeySettings.helpModal.step3Title")}</div>
          <p className="text-muted-foreground">{t("home.apiKeySettings.helpModal.step3Body")}</p>
        </div>
        <div>
          <div className="font-medium">4. {t("home.apiKeySettings.helpModal.step4Title")}</div>
          <p className="text-muted-foreground">{t("home.apiKeySettings.helpModal.step4Body")}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/40 p-4">
          <div className="font-medium">{t("home.apiKeySettings.helpModal.referenceTitle")}</div>
          <p className="mt-2 text-muted-foreground">{t("home.apiKeySettings.helpModal.referenceBody")}</p>
          <div className="mt-3 flex flex-col gap-2">
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/app-management/app-instance/get-app-instance" target="_blank" rel="noreferrer">
              {t("home.apiKeySettings.helpModal.referenceAppInstance")}
            </a>
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/business-solutions/events/registration/ticketing/tickets/introduction" target="_blank" rel="noreferrer">
              {t("home.apiKeySettings.helpModal.referenceTickets")}
            </a>
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/business-management/app-installation/skills/list-installed-apps" target="_blank" rel="noreferrer">
              {t("home.apiKeySettings.helpModal.referenceApps")}
            </a>
          </div>
        </div>
      </HelpModal>
    </>
  );
}
