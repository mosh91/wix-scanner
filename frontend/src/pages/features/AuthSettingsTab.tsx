import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpModal } from "@/components/HelpModal";
import { useHelpModal } from "@/hooks/useHelpModal";
import { useAdminData } from "@/context/AdminDataContext";
import { refreshAuthToken, testAuthConnection, saveApiKeySettings, testApiKeyConnection } from "@/services/scannerApi";

export default function AuthSettingsTab() {
  const { t } = useTranslation();
  const {
    authTokenStatus, setAuthTokenStatus, loadAuthSettings, loadingAuthSettings, selectedAuthMode,
    apiKeySettings, setApiKeySettings, loadApiKeySettings, loadingApiKeySettings,
  } = useAdminData();
  const help = useHelpModal();
  const credentialsGuide = useHelpModal();
  const apiKeyModal = useHelpModal();

  const [apiKeyValue, setApiKeyValue] = useState("");
  const [wixAccountId, setWixAccountId] = useState("");
  const [testingApiKey, setTestingApiKey] = useState(false);
  const [savingApiKey, setSavingApiKey] = useState(false);
  const [apiKeyTestResult, setApiKeyTestResult] = useState<{ ok: boolean; message: string; tested_at: string } | null>(null);

  useEffect(() => {
    setWixAccountId(apiKeySettings?.wix_account_id ?? "");
  }, [apiKeySettings]);

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
              <CardTitle>{t("home.authSettings.title")}</CardTitle>
              <CardDescription>{t("home.authSettings.description")}</CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button className="h-8 px-3 text-xs" variant="outline" onClick={credentialsGuide.open}>
                {t("home.authModeGuide.helpButton")}
              </Button>
              <Button className="h-8 px-3 text-xs" variant="outline" onClick={apiKeyModal.open}>
                {t("home.apiKeySettings.title")}
              </Button>
              <Button className="h-8 px-3 text-xs" variant="outline" onClick={help.open}>
                {t("home.authSettings.helpButton")}
              </Button>
            </div>
          </div>
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

      <HelpModal
        open={credentialsGuide.isOpen}
        onClose={credentialsGuide.close}
        title={t("home.credentials.helpModal.title")}
        subtitle={t("home.credentials.helpModal.subtitle")}
      >
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-border/70 bg-muted/40 p-4 text-sm">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.authModeGuide.selectedLabel")}</div>
            <div className="mt-1 font-medium">
              {selectedAuthMode ? t(`home.authModeGuide.modes.${selectedAuthMode}`) : t("home.authModeGuide.loading")}
            </div>
          </div>
          <div className="rounded-lg border border-border/70 bg-muted/40 p-4 text-sm">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">{t("home.authModeGuide.switchLabel")}</div>
            <div className="mt-1 font-medium">{t("home.authModeGuide.switchHint")}</div>
          </div>
        </div>
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
      </HelpModal>

      <HelpModal
        open={apiKeyModal.isOpen}
        onClose={apiKeyModal.close}
        title={t("home.apiKeySettings.title")}
        subtitle={t("home.apiKeySettings.description")}
      >
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
      </HelpModal>

      <HelpModal
        open={help.isOpen}
        onClose={help.close}
        title={t("home.authSettings.helpModal.title")}
        subtitle={t("home.authSettings.helpModal.subtitle")}
      >
        <div>
          <div className="font-medium">1. {t("home.authSettings.helpModal.step1Title")}</div>
          <p className="text-muted-foreground">{t("home.authSettings.helpModal.step1Body")}</p>
        </div>
        <div>
          <div className="font-medium">2. {t("home.authSettings.helpModal.step2Title")}</div>
          <p className="text-muted-foreground">{t("home.authSettings.helpModal.step2Body")}</p>
        </div>
        <div>
          <div className="font-medium">3. {t("home.authSettings.helpModal.step3Title")}</div>
          <p className="text-muted-foreground">{t("home.authSettings.helpModal.step3Body")}</p>
        </div>
        <div>
          <div className="font-medium">4. {t("home.authSettings.helpModal.step4Title")}</div>
          <p className="text-muted-foreground">{t("home.authSettings.helpModal.step4Body")}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/40 p-4">
          <div className="font-medium">{t("home.authSettings.helpModal.referenceTitle")}</div>
          <div className="mt-3 flex flex-col gap-2">
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/sdk/auth/about-oauth" target="_blank" rel="noreferrer">
              {t("home.authSettings.helpModal.referenceOAuth")}
            </a>
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/app-management/app-instance/get-app-instance" target="_blank" rel="noreferrer">
              {t("home.authSettings.helpModal.referenceInstance")}
            </a>
          </div>
        </div>
      </HelpModal>
    </>
  );
}
