import * as XLSX from 'xlsx'
import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'

function safeFilename(title: string): string {
  return (title || 'table-export')
    .trim()
    .replace(/[^a-z0-9 _-]/gi, '')
    .replace(/\s+/g, '-')
    .slice(0, 80) || 'table-export'
}

/** Export a rendered HTML `<table>` element as an .xlsx workbook — reads
 * whatever is currently on screen, so it works generically for any table
 * built from `DataTable` without each call site needing to pass row data. */
export function exportTableToExcel(table: HTMLTableElement, title: string): void {
  const wb = XLSX.utils.table_to_book(table, { raw: false })
  XLSX.writeFile(wb, `${safeFilename(title)}.xlsx`)
}

/** Export a rendered HTML `<table>` element as a landscape PDF. */
export function exportTableToPdf(table: HTMLTableElement, title: string): void {
  const doc = new jsPDF({ orientation: 'landscape', unit: 'pt' })
  const marginTop = 36
  doc.setFontSize(12)
  doc.text(title, 24, 24)
  autoTable(doc, {
    html: table,
    startY: marginTop,
    margin: { left: 14, right: 14 },
    styles: { fontSize: 7, cellPadding: 4 },
    headStyles: { fillColor: [30, 41, 59], textColor: [226, 232, 240] },
    theme: 'grid',
  })
  doc.save(`${safeFilename(title)}.pdf`)
}
