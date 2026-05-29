import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function HomePage() {
  const { t } = useTranslation();

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
    </section>
  );
}
