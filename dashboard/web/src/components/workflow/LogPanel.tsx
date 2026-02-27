import type { CSSProperties } from 'react';

export function LogPanel({
  text,
  style,
}: {
  text: string;
  style?: CSSProperties;
}) {
  return (
    <pre className="manual-log" style={style}>
      {text}
    </pre>
  );
}
