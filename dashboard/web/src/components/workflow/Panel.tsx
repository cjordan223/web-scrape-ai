import type { CSSProperties, ReactNode } from 'react';

type WorkflowPanelProps = {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  headerStyle?: CSSProperties;
};

function cx(...parts: Array<string | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function WorkflowPanel({ title, right, children, className, style, headerStyle }: WorkflowPanelProps) {
  return (
    <div className={cx('panel', className)} style={style}>
      {(title || right) ? (
        <div className="panel-header" style={headerStyle}>
          {title ? <div className="panel-title">{title}</div> : <div />}
          {right}
        </div>
      ) : null}
      {children}
    </div>
  );
}
