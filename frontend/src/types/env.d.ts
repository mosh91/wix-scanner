/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_NAME?: string;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DEFAULT_LOCALE?: string;
  readonly VITE_SCANNER_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
