import { useState, type ComponentPropsWithoutRef, type ReactNode } from "react";

type Props = Omit<ComponentPropsWithoutRef<"details">, "open" | "onToggle"> & {
  summary: ReactNode;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
};

/** Closed sections do not initialize charts or build large tables. */
export default function Disclosure({ summary, children, expanded, onExpandedChange, ...props }: Props) {
  const [localExpanded, setLocalExpanded] = useState(false);
  const open = expanded ?? localExpanded;
  return <details {...props} open={open} onToggle={(event) => {
    const next = event.currentTarget.open;
    if (next === open) return;
    if (onExpandedChange) onExpandedChange(next);
    else setLocalExpanded(next);
  }}>
    <summary>{summary}</summary>
    {open && children}
  </details>;
}
