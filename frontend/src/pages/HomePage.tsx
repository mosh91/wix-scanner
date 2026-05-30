import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchWebhookHistory,
  retryWebhookDelivery,
  type WebhookDeliveryRecord,
} from "@/services/scannerApi";

export default function HomePage() {
  const { t } = useTranslation();
  const [webhookHistory, setWebhookHistory] = useState<WebhookDeliveryRecord[]>([]);
  const [loadingWebhooks, setLoadingWebhooks] = useState(false);

  const loadWebhookHistory = async () => {
    setLoadingWebhooks(true);
    try {
      const rows = await fetchWebhookHistory(12);
      setWebhookHistory(rows);
    } catch {
      toast.error("No se pudo cargar historial de webhooks");
    } finally {
      setLoadingWebhooks(false);
    }
  };

  useEffect(() => {
    void loadWebhookHistory();
  }, []);

  const handleRetry = async (deliveryId: number) => {
    try {
      await retryWebhookDelivery(deliveryId);
      toast.success("Reintento de webhook ejecutado");
      await loadWebhookHistory();
    } catch {
      toast.error("No se pudo reintentar el webhook");
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
          <CardTitle>Developer-ready surfaces</CardTitle>
          <CardDescription>
            FastAPI health, React routes, Tailwind tokens, and reusable UI primitives are in place.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2 text-sm text-muted-foreground">
          <Badge variant="outline">/api/health</Badge>
          <Badge variant="outline">Toaster</Badge>
          <Badge variant="outline">Route placeholders</Badge>
        </CardContent>
      </Card>

      <Card className="border-border/70 md:col-span-2">
        <CardHeader>
          <CardTitle>Webhook Delivery History</CardTitle>
          <CardDescription>
            Monitor Wix mobile check-in webhooks and trigger manual retries for failed deliveries.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={() => void loadWebhookHistory()} disabled={loadingWebhooks}>
              {loadingWebhooks ? "Refreshing..." : "Refresh"}
            </Button>
          </div>
          {webhookHistory.length === 0 ? (
            <p className="text-sm text-muted-foreground">No webhook deliveries yet.</p>
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
                    Retry
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
