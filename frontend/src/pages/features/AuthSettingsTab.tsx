import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpModal } from "@/components/HelpModal";
import { useHelpModal } from "@/hooks/useHelpModal";
import { useAdminData } from "@/context/AdminDataContext";
import { refreshAuthToken, testAuthConnection } from "@/services/scannerApi";

export default function AuthSettingsTab() {
  const { t } = useTranslation();
  const { authTokenStatus, setAuthTokenStatus, loadAuthSettings, loadingAuthSettings } = useAdminData();
  const help = useHelpModal();

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

  return (
    <>
      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>{t("home.authSettings.title")}</CardTitle>
              <CardDescription>{t("home.authSettings.description")}</CardDescription>
            </div>
            <Button className="h-8 px-3 text-xs" variant="outline" onClick={help.open}>
              {t("home.authSettings.helpButton")}
            </Button>
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
