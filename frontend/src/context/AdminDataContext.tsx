import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  fetchWebhookHistory,
  getApiKeySettings,
  getAuthTokenStatus,
  listLatestScopeAudits,
  listSiteEventBindings,
  listVerifiedEvents,
  type ApiKeySettingsResponse,
  type AuthTokenStatusResponse,
  type SiteEventBindingRecord,
  type VerifiedEventRecord,
  type WebhookDeliveryRecord,
  type WixScopeAuditRecord,
} from "@/services/scannerApi";

export interface DashboardStats {
  verifiedBindings: number;
  warningScopes: number;
  webhookFailures: number;
  totalBindings: number;
  totalVerifiedEvents: number;
}

interface AdminDataContextValue {
  // Site/event bindings (hero stats, dashboard, integrations, readiness)
  bindings: SiteEventBindingRecord[];
  setBindings: Dispatch<SetStateAction<SiteEventBindingRecord[]>>;
  verifiedEvents: VerifiedEventRecord[];
  scopeAudits: Record<string, WixScopeAuditRecord>;
  loadingBindings: boolean;
  loadBindings: () => Promise<void>;

  // Webhook deliveries (hero stats, dashboard, deliveries)
  webhookHistory: WebhookDeliveryRecord[];
  loadingWebhooks: boolean;
  loadWebhookHistory: () => Promise<void>;

  // Auth token settings (integrations guide, credentials, auth-settings, redirect)
  authTokenStatus: AuthTokenStatusResponse | null;
  setAuthTokenStatus: Dispatch<SetStateAction<AuthTokenStatusResponse | null>>;
  loadingAuthSettings: boolean;
  loadAuthSettings: () => Promise<void>;

  // API key settings (integrations guide, credentials, api-key-management, redirect)
  apiKeySettings: ApiKeySettingsResponse | null;
  setApiKeySettings: Dispatch<SetStateAction<ApiKeySettingsResponse | null>>;
  loadingApiKeySettings: boolean;
  loadApiKeySettings: () => Promise<void>;

  // Derived
  selectedAuthMode: string | null;
  dashboardStats: DashboardStats;
}

const AdminDataContext = createContext<AdminDataContextValue | null>(null);

export function AdminDataProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();

  const [bindings, setBindings] = useState<SiteEventBindingRecord[]>([]);
  const [verifiedEvents, setVerifiedEvents] = useState<VerifiedEventRecord[]>([]);
  const [scopeAudits, setScopeAudits] = useState<Record<string, WixScopeAuditRecord>>({});
  const [loadingBindings, setLoadingBindings] = useState(false);

  const [webhookHistory, setWebhookHistory] = useState<WebhookDeliveryRecord[]>([]);
  const [loadingWebhooks, setLoadingWebhooks] = useState(false);

  const [authTokenStatus, setAuthTokenStatus] = useState<AuthTokenStatusResponse | null>(null);
  const [loadingAuthSettings, setLoadingAuthSettings] = useState(false);
  const [apiKeySettings, setApiKeySettings] = useState<ApiKeySettingsResponse | null>(null);
  const [loadingApiKeySettings, setLoadingApiKeySettings] = useState(false);

  const loadBindings = useCallback(async () => {
    setLoadingBindings(true);
    try {
      const [bindingRows, verifiedRows] = await Promise.all([
        listSiteEventBindings(),
        listVerifiedEvents(),
      ]);
      setBindings(bindingRows);
      setVerifiedEvents(verifiedRows);

      const latestScopeRows = await listLatestScopeAudits();
      const map = latestScopeRows.reduce<Record<string, WixScopeAuditRecord>>((acc, row) => {
        acc[row.binding_id] = row;
        return acc;
      }, {});
      setScopeAudits(map);
    } catch {
      toast.error(t("home.bindings.loadError"));
    } finally {
      setLoadingBindings(false);
    }
  }, [t]);

  const loadWebhookHistory = useCallback(async () => {
    setLoadingWebhooks(true);
    try {
      const rows = await fetchWebhookHistory(12);
      setWebhookHistory(rows);
    } catch {
      toast.error(t("home.webhook.loadError"));
    } finally {
      setLoadingWebhooks(false);
    }
  }, [t]);

  const loadAuthSettings = useCallback(async () => {
    setLoadingAuthSettings(true);
    try {
      const status = await getAuthTokenStatus();
      setAuthTokenStatus(status);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.authSettings.loadError"));
    } finally {
      setLoadingAuthSettings(false);
    }
  }, [t]);

  const loadApiKeySettings = useCallback(async () => {
    setLoadingApiKeySettings(true);
    try {
      const status = await getApiKeySettings();
      setApiKeySettings(status);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("home.apiKeySettings.loadError"));
    } finally {
      setLoadingApiKeySettings(false);
    }
  }, [t]);

  useEffect(() => {
    void loadWebhookHistory();
    void loadBindings();
    void loadAuthSettings();
    void loadApiKeySettings();
  }, [loadWebhookHistory, loadBindings, loadAuthSettings, loadApiKeySettings]);

  const selectedAuthMode = authTokenStatus?.auth_mode ?? apiKeySettings?.auth_mode ?? null;

  const dashboardStats = useMemo<DashboardStats>(() => {
    const verifiedBindings = bindings.filter((item) => item.status === "verified").length;
    const warningScopes = Object.values(scopeAudits).filter((item) => item.status === "warning").length;
    const webhookFailures = webhookHistory.filter((item) => item.status !== "delivered").length;
    return {
      verifiedBindings,
      warningScopes,
      webhookFailures,
      totalBindings: bindings.length,
      totalVerifiedEvents: verifiedEvents.length,
    };
  }, [bindings, scopeAudits, webhookHistory, verifiedEvents.length]);

  const value = useMemo<AdminDataContextValue>(
    () => ({
      bindings,
      setBindings,
      verifiedEvents,
      scopeAudits,
      loadingBindings,
      loadBindings,
      webhookHistory,
      loadingWebhooks,
      loadWebhookHistory,
      authTokenStatus,
      setAuthTokenStatus,
      loadingAuthSettings,
      loadAuthSettings,
      apiKeySettings,
      setApiKeySettings,
      loadingApiKeySettings,
      loadApiKeySettings,
      selectedAuthMode,
      dashboardStats,
    }),
    [
      bindings,
      verifiedEvents,
      scopeAudits,
      loadingBindings,
      loadBindings,
      webhookHistory,
      loadingWebhooks,
      loadWebhookHistory,
      authTokenStatus,
      loadingAuthSettings,
      loadAuthSettings,
      apiKeySettings,
      loadingApiKeySettings,
      loadApiKeySettings,
      selectedAuthMode,
      dashboardStats,
    ],
  );

  return <AdminDataContext.Provider value={value}>{children}</AdminDataContext.Provider>;
}

export function useAdminData(): AdminDataContextValue {
  const ctx = useContext(AdminDataContext);
  if (!ctx) {
    throw new Error("useAdminData must be used within an AdminDataProvider");
  }
  return ctx;
}
