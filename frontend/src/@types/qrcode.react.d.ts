declare module 'qrcode.react' {
  import * as React from 'react';
  type QRCodeProps = React.SVGProps<SVGElement> & {
    value: string;
    size?: number;
    level?: 'L'|'M'|'Q'|'H';
    includeMargin?: boolean;
    renderAs?: 'canvas' | 'svg';
  };
  export const QRCodeCanvas: React.FC<QRCodeProps>;
  export const QRCodeSVG: React.FC<QRCodeProps>;
  // some builds provide a default; keep a fallback type for TS consumers that import default
  const _default: React.FC<QRCodeProps>;
  export default _default;
}
