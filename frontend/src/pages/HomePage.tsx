import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AdminDataProvider, useAdminData } from "@/context/AdminDataContext";

const TAB_KEYS = [
  "integrations",
  "deliveries",
  "readiness",
  "sync-controls",
  "reconciliation",
  "auth-settings",
  "relay-management",
  "secret-rotation",
  "kiosk-qr",
] as const;

function tabLinkClassName({ isActive }: { isActive: boolean }) {
  return (
    "inline-flex items-center justify-center rounded-xl px-4 py-2 text-sm font-medium transition-colors " +
    (isActive
      ? "bg-primary text-primary-foreground hover:bg-primary/90"
      : "hover:bg-accent hover:text-accent-foreground")
  );
}

function HeroStats() {
  const { t } = useTranslation();
  const { dashboardStats } = useAdminData();

  return (
    <Card className="border-border/70 bg-[linear-gradient(135deg,rgba(13,40,75,0.92)_0%,rgba(25,102,165,0.92)_100%)] text-white">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Badge className="w-fit border-white/40 bg-white/15 text-white" variant="outline">
            {t("home.hero.badge")}
          </Badge>
          <Button asChild className="bg-white text-slate-900 hover:bg-white/90">
            <NavLink to="/operator">{t("home.hero.primaryAction")}</NavLink>
          </Button>
        </div>
        <CardTitle className="text-2xl md:text-3xl">{t("home.hero.title")}</CardTitle>
        <CardDescription className="text-white/80">{t("home.hero.description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-3">
        <div className="rounded-xl border border-white/20 bg-white/10 px-4 py-3">
          <div className="text-xs uppercase tracking-wide text-white/70">{t("home.metrics.verifiedBindings")}</div>
          <div className="text-2xl font-semibold">{dashboardStats.verifiedBindings}/{dashboardStats.totalBindings}</div>
        </div>
        <div className="rounded-xl border border-white/20 bg-white/10 px-4 py-3">
          <div className="text-xs uppercase tracking-wide text-white/70">{t("home.metrics.scopeWarnings")}</div>
          <div className="text-2xl font-semibold">{dashboardStats.warningScopes}</div>
        </div>
        <div className="rounded-xl border border-white/20 bg-white/10 px-4 py-3">
          <div className="text-xs uppercase tracking-wide text-white/70">{t("home.metrics.verifiedEvents")}</div>
          <div className="text-2xl font-semibold">{dashboardStats.totalVerifiedEvents}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function HomeShell() {
  const { t } = useTranslation();

  return (
    <section className="space-y-5">
      <HeroStats />

      <div className="flex flex-wrap gap-2 rounded-2xl border border-border/70 bg-card p-2">
        {TAB_KEYS.map((tab) => (
          <NavLink key={tab} to={`/${tab}`} className={tabLinkClassName}>
            {t(`home.tabs.${tab}`)}
          </NavLink>
        ))}
      </div>

      <Outlet />
    </section>
  );
}

export default function HomePage() {
  return (
    <AdminDataProvider>
      <HomeShell />
    </AdminDataProvider>
  );
}
