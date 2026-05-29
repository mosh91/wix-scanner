import { NavLink, Route, Routes } from "react-router-dom";
import { ScanBarcode, ShieldCheck, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import HomePage from "@/pages/HomePage";
import OperatorPage from "@/pages/OperatorPage";

const navLinkClassName = ({ isActive }: { isActive: boolean }) =>
  [
    "inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-primary text-primary-foreground"
      : "bg-muted text-muted-foreground hover:text-foreground",
  ].join(" ");

export default function App() {
  const { t, i18n } = useTranslation();
  const location = useLocation();

  if (location.pathname === "/operator") {
    return (
      <Routes>
        <Route path="/operator" element={<OperatorPage />} />
      </Routes>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border/70 bg-card/80 backdrop-blur">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex size-11 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
              <ScanBarcode aria-hidden="true" className="size-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold tracking-tight">{t("app.name")}</h1>
                <Badge variant="secondary">{i18n.language.toUpperCase()}</Badge>
              </div>
              <p className="text-sm text-muted-foreground">{t("app.tagline")}</p>
            </div>
          </div>

          <nav className="flex items-center gap-2">
            <NavLink to="/" className={navLinkClassName} end>
              <Sparkles aria-hidden="true" className="size-4" />
              {t("nav.home")}
            </NavLink>
            <NavLink to="/operator" className={navLinkClassName}>
              <ShieldCheck aria-hidden="true" className="size-4" />
              {t("nav.operator")}
            </NavLink>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-6 py-8">
        <Card className="border-border/70 shadow-sm">
          <CardHeader>
            <CardTitle>{t("layout.title")}</CardTitle>
            <CardDescription>{t("layout.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant="outline">FastAPI</Badge>
              <Badge variant="outline">React + Vite</Badge>
              <Badge variant="outline">Tailwind</Badge>
              <Badge variant="outline">shadcn/ui</Badge>
              <Badge variant="outline">i18next</Badge>
              <Badge variant="outline">Sonner</Badge>
            </div>
            <Separator className="my-6" />
            <Button asChild>
              <NavLink to="/operator">{t("layout.primaryAction")}</NavLink>
            </Button>
          </CardContent>
        </Card>

        <div className="mt-8">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/operator" element={<OperatorPage />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
