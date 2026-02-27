import type { CSSProperties, ReactNode } from 'react';

function cx(...parts: Array<string | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function FilterToolbar({
  children,
  className,
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div className={cx('filters', className)} style={style}>
      {children}
    </div>
  );
}
