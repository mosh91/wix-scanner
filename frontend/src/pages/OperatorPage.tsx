import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function OperatorPage() {
  const { t } = useTranslation();

  return (
    <Card className="border-border/70">
      <CardHeader>
        <Badge className="w-fit" variant="secondary">
          {t("nav.operator")}
        </Badge>
        <CardTitle>{t("operator.title")}</CardTitle>
        <CardDescription>{t("operator.description")}</CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        The kiosk flow, scanner hooks, and scan state machine can land here next.
      </CardContent>
    </Card>
  );
}
