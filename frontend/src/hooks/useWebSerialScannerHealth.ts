// useWebSerialScanner handles both port management and scan reading in one hook.
// Import directly from there; this file re-exports the result type for callers
// that only care about the health shape (e.g. type declarations, tests).
export type { WebSerialScannerResult as WebSerialStatus } from "./useWebSerialScanner";
export { useWebSerialScanner } from "./useWebSerialScanner";
