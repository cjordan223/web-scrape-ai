import type { CSSProperties, ReactNode } from 'react';

function cx(...parts: Array<string | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function ActionBar({
  children,
  className,
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div className={cx('workflow-action-bar', className)} style={style}>
      {children}
    </div>
  );
}
