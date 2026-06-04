// Minimal Web Serial API type declarations.
// The full spec: https://wicg.github.io/serial/

interface SerialPortInfo {
  usbVendorId?: number;
  usbProductId?: number;
}

interface SerialOptions {
  baudRate: number;
  dataBits?: 7 | 8;
  stopBits?: 1 | 2;
  parity?: "none" | "even" | "odd";
  bufferSize?: number;
  flowControl?: "none" | "hardware";
}

interface SerialPort extends EventTarget {
  readonly readable: ReadableStream<Uint8Array> | null;
  readonly writable: WritableStream<BufferSource> | null;
  open(options: SerialOptions): Promise<void>;
  close(): Promise<void>;
  getInfo(): SerialPortInfo;
}

interface SerialConnectionEvent extends Event {
  readonly port: SerialPort;
}

interface SerialPortRequestOptions {
  filters?: Array<{ usbVendorId?: number; usbProductId?: number }>;
}

interface Serial extends EventTarget {
  getPorts(): Promise<SerialPort[]>;
  requestPort(options?: SerialPortRequestOptions): Promise<SerialPort>;
  addEventListener(type: "connect", listener: (event: SerialConnectionEvent) => void, options?: boolean | AddEventListenerOptions): void;
  addEventListener(type: "disconnect", listener: (event: SerialConnectionEvent) => void, options?: boolean | AddEventListenerOptions): void;
  removeEventListener(type: "connect", listener: (event: SerialConnectionEvent) => void, options?: boolean | EventListenerOptions): void;
  removeEventListener(type: "disconnect", listener: (event: SerialConnectionEvent) => void, options?: boolean | EventListenerOptions): void;
}

interface Navigator {
  readonly serial: Serial;
}
