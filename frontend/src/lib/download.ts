/** Export underlying values, preserving precision and protecting spreadsheet cells. */
export function fileStem(name: string): string {
  return name.replace(/[^a-z0-9_-]+/gi, "-").replace(/^-+|-+$/g, "").slice(0, 100) || "zone-analytics";
}

export function csvForRows(rows: Record<string, unknown>[], columns: string[], labels: Record<string, string> = {}): string {
  const cell = (value: unknown) => {
    let text = value == null ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);
    // Quoting alone does not stop spreadsheet formula execution. Keep numeric
    // values numeric, but neutralize formula-like strings, including whitespace.
    if (typeof value === "string" && (/^\s*[=+\-@]/.test(text) || /^[\t\r\n]/.test(text))) text = "'" + text;
    return `"${text.replaceAll('"', '""')}"`;
  };
  return "\uFEFF" + [columns.map(c => cell(labels[c] ?? c)).join(","),
    ...rows.map(row => columns.map(c => cell(row[c])).join(","))].join("\r\n") + "\r\n";
}

export function downloadCsv(rows: Record<string, unknown>[], columns: string[], name: string, labels?: Record<string, string>) {
  const url = URL.createObjectURL(new Blob([csvForRows(rows, columns, labels)], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${fileStem(name)}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
