import type { CSSProperties } from 'react';

export function LoadingState({ style }: { style?: CSSProperties }) {
  return (
    <div className="loading" style={style}>
      <div className="spinner"></div>
    </div>
  );
}

export function EmptyState({
  text,
  icon,
  style,
}: {
  text: string;
  icon?: string;
  style?: CSSProperties;
}) {
  return (
    <div className="empty" style={style}>
      {icon ? <div className="empty-icon">{icon}</div> : null}
      <div className="empty-text">{text}</div>
    </div>
  );
}
