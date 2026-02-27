import type { CSSProperties, ReactNode } from 'react';

type SectionProps = {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
};

function cx(...parts: Array<string | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function PageView({ children }: { children: ReactNode }) {
  return <div className="view-container">{children}</div>;
}

export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <div className="page-title">{title}</div>
        {subtitle ? <div className="page-subtitle">{subtitle}</div> : null}
      </div>
      {right ? <div className="page-header-right">{right}</div> : null}
    </div>
  );
}

export function PagePrimary({ children, className, style }: SectionProps) {
  return (
    <section className={cx('workflow-primary', className)} style={style}>
      {children}
    </section>
  );
}

export function PageSecondary({ children, className, style }: SectionProps) {
  return (
    <section className={cx('workflow-secondary', className)} style={style}>
      {children}
    </section>
  );
}
