import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpModal } from "@/components/HelpModal";
import { useHelpModal } from "@/hooks/useHelpModal";
import { useAdminData } from "@/context/AdminDataContext";

export default function DashboardTab() {
  const { t } = useTranslation();
  const { dashboardStats, loadBindings, loadWebhookHistory } = useAdminData();
  const help = useHelpModal();

  return (
    <>
      <div className="space-y-3">
        <div className="flex justify-end">
          <Button className="h-8 px-3 text-xs" variant="outline" onClick={help.open}>
            {t("home.dashboard.helpButton")}
          </Button>
        </div>
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
      </div>

      <HelpModal
        open={help.isOpen}
        onClose={help.close}
        title={t("home.dashboard.helpModal.title")}
        subtitle={t("home.dashboard.helpModal.subtitle")}
      >
        <div>
          <div className="font-medium">1. {t("home.dashboard.helpModal.step1Title")}</div>
          <p className="text-muted-foreground">{t("home.dashboard.helpModal.step1Body")}</p>
        </div>
        <div>
          <div className="font-medium">2. {t("home.dashboard.helpModal.step2Title")}</div>
          <p className="text-muted-foreground">{t("home.dashboard.helpModal.step2Body")}</p>
        </div>
        <div>
          <div className="font-medium">3. {t("home.dashboard.helpModal.step3Title")}</div>
          <p className="text-muted-foreground">{t("home.dashboard.helpModal.step3Body")}</p>
        </div>
        <div>
          <div className="font-medium">4. {t("home.dashboard.helpModal.step4Title")}</div>
          <p className="text-muted-foreground">{t("home.dashboard.helpModal.step4Body")}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/40 p-4">
          <div className="font-medium">{t("home.dashboard.helpModal.referenceTitle")}</div>
          <div className="mt-3 flex flex-col gap-2">
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/app-management/app-instance/get-app-instance" target="_blank" rel="noreferrer">
              {t("home.dashboard.helpModal.referenceInstance")}
            </a>
            <a className="text-primary underline-offset-4 hover:underline" href="https://support.wix.com/en/article/wix-events-creating-an-event" target="_blank" rel="noreferrer">
              {t("home.dashboard.helpModal.referenceEvents")}
            </a>
          </div>
        </div>
      </HelpModal>
    </>
  );
}
