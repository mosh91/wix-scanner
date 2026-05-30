import { NavLink, Route, Routes } from "react-router-dom";
import { LayoutDashboard, ScanBarcode, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import HomePage from "@/pages/HomePage";
import OperatorPage from "@/pages/OperatorPage";

const navLinkClassName = ({ isActive }: { isActive: boolean }) =>
  [
    "inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-primary text-primary-foreground"
        : "bg-white/70 text-muted-foreground hover:text-foreground",
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
      <header className="border-b border-border/70 bg-white/80 backdrop-blur">
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
              <LayoutDashboard aria-hidden="true" className="size-4" />
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
        <div className="mb-4 flex items-center justify-between">
          <Badge variant="outline">{t("layout.controlCenter")}</Badge>
        </div>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/operator" element={<OperatorPage />} />
        </Routes>
      </main>
    </div>
  );
}
