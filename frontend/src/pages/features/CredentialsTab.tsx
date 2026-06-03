import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpModal } from "@/components/HelpModal";
import { useHelpModal } from "@/hooks/useHelpModal";
import { useAdminData } from "@/context/AdminDataContext";

export default function CredentialsTab() {
  const { t } = useTranslation();
  const { selectedAuthMode } = useAdminData();
  const help = useHelpModal();

  return (
    <>
      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>{t("home.authModeGuide.title")}</CardTitle>
            <Button className="h-8 px-3 text-xs" variant="outline" onClick={help.open}>
              {t("home.authModeGuide.helpButton")}
            </Button>
          </div>
          <CardDescription>{t("home.authModeGuide.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
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

          <div className="space-y-3 rounded-xl border border-border/70 bg-background p-4 text-sm leading-6">
            <div>
              <div className="font-medium">1. {t("home.authModeGuide.oauthTitle")}</div>
              <p className="text-muted-foreground">{t("home.authModeGuide.oauthBody")}</p>
            </div>
            <div>
              <div className="font-medium">2. {t("home.authModeGuide.apiKeyTitle")}</div>
              <p className="text-muted-foreground">{t("home.authModeGuide.apiKeyBody")}</p>
            </div>
            <div>
              <div className="font-medium">3. {t("home.authModeGuide.oauthTitle")}</div>
              <p className="text-muted-foreground">{t("home.authModeGuide.referenceBody")}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <HelpModal
        open={help.isOpen}
        onClose={help.close}
        title={t("home.credentials.helpModal.title")}
        subtitle={t("home.credentials.helpModal.subtitle")}
      >
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
    </>
  );
}
