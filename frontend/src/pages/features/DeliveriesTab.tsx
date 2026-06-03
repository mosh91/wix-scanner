import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HelpModal } from "@/components/HelpModal";
import { useHelpModal } from "@/hooks/useHelpModal";
import { useAdminData } from "@/context/AdminDataContext";
import { retryWebhookDelivery } from "@/services/scannerApi";

export default function DeliveriesTab() {
  const { t } = useTranslation();
  const { webhookHistory, loadingWebhooks, loadWebhookHistory } = useAdminData();
  const help = useHelpModal();

  const handleRetry = async (deliveryId: number) => {
    try {
      await retryWebhookDelivery(deliveryId);
      toast.success(t("home.webhook.retrySuccess"));
      await loadWebhookHistory();
    } catch {
      toast.error(t("home.webhook.retryError"));
    }
  };

  return (
    <>
      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle>{t("home.webhook.title")}</CardTitle>
              <CardDescription>{t("home.webhook.description")}</CardDescription>
            </div>
            <Button className="h-8 px-3 text-xs" variant="outline" onClick={help.open}>
              {t("home.webhook.helpButton")}
            </Button>
          </div>
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
                  <Button className="h-8 px-3 text-xs" variant="outline" onClick={() => void handleRetry(item.id)}>
                    {t("home.webhook.retry")}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <HelpModal
        open={help.isOpen}
        onClose={help.close}
        title={t("home.webhook.helpModal.title")}
        subtitle={t("home.webhook.helpModal.subtitle")}
      >
        <div>
          <div className="font-medium">1. {t("home.webhook.helpModal.step1Title")}</div>
          <p className="text-muted-foreground">{t("home.webhook.helpModal.step1Body")}</p>
        </div>
        <div>
          <div className="font-medium">2. {t("home.webhook.helpModal.step2Title")}</div>
          <p className="text-muted-foreground">{t("home.webhook.helpModal.step2Body")}</p>
        </div>
        <div>
          <div className="font-medium">3. {t("home.webhook.helpModal.step3Title")}</div>
          <p className="text-muted-foreground">{t("home.webhook.helpModal.step3Body")}</p>
        </div>
        <div>
          <div className="font-medium">4. {t("home.webhook.helpModal.step4Title")}</div>
          <p className="text-muted-foreground">{t("home.webhook.helpModal.step4Body")}</p>
        </div>
        <div className="rounded-lg border border-border/70 bg-muted/40 p-4">
          <div className="font-medium">{t("home.webhook.helpModal.referenceTitle")}</div>
          <div className="mt-3 flex flex-col gap-2">
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/business-solutions/events/registration/ticketing/tickets/introduction" target="_blank" rel="noreferrer">
              {t("home.webhook.helpModal.referenceTickets")}
            </a>
            <a className="text-primary underline-offset-4 hover:underline" href="https://dev.wix.com/docs/api-reference/business-solutions/events/skills/list-events" target="_blank" rel="noreferrer">
              {t("home.webhook.helpModal.referenceEvents")}
            </a>
          </div>
        </div>
      </HelpModal>
    </>
  );
}
