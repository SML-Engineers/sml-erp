import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { formatDecimal, sumDecimal } from "../lib/decimal";

export interface Column<T> {
  id: string;
  header: string;
  /** Value used for sorting, searching and (for money) totals. */
  value: (row: T) => string | number | boolean | null | undefined;
  /** How to show the cell; defaults to the value. */
  cell?: (row: T) => ReactNode;
  /** Money or quantity: right-aligned, thousands separators, total in the footer. */
  money?: boolean;
  sortable?: boolean;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string | number;
  /** Starting page size; "All" shows everything (as in the current system). */
  pageSize?: number | "all";
  searchable?: boolean;
  emptyText?: string;
  label?: string;
}

const PAGE_SIZES = [10, 25, 50] as const;

/**
 * The table every list in the ERP uses: search, sortable columns, page sizes,
 * "Showing 1 to 10 of 42", Previous / Next, and exact totals for money columns.
 */
export default function DataTable<T>({
  rows,
  columns,
  rowKey,
  pageSize = 25,
  searchable = true,
  emptyText,
  label,
}: Props<T>) {
  const { t } = useTranslation();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [search, setSearch] = useState("");
  const [size, setSize] = useState<number | "all">(pageSize);
  const [page, setPage] = useState(0);
  const perPageSetting = size === "all" ? Math.max(rows.length, 1) : size;

  const defs: ColumnDef<T>[] = columns.map((c): ColumnDef<T> => ({
    id: c.id,
    header: c.header,
    accessorFn: (row: T) => c.value(row) ?? "",
    enableSorting: c.sortable !== false,
    sortingFn: c.money
      ? (a, b) => compareDecimal(String(a.getValue(c.id)), String(b.getValue(c.id)))
      : ("alphanumeric" as const),
    cell: (info) => {
      const row = info.row.original;
      if (c.cell) return c.cell(row);
      const v = c.value(row);
      return c.money ? formatDecimal(v === null || v === undefined ? "" : String(v)) : String(v ?? "");
    },
  }));

  const table = useReactTable({
    data: rows,
    columns: defs,
    state: {
      sorting,
      globalFilter: search,
      pagination: { pageIndex: page, pageSize: perPageSetting },
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setSearch,
    onPaginationChange: (updater) =>
      setPage((current) => {
        const state = { pageIndex: current, pageSize: perPageSetting };
        return (typeof updater === "function" ? updater(state) : updater).pageIndex;
      }),
    globalFilterFn: "includesString",
    getRowId: (row) => String(rowKey(row)),
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  const filtered = table.getFilteredRowModel().rows;
  const visible = table.getRowModel().rows;
  const { pageIndex, pageSize: perPage } = table.getState().pagination;
  const first = filtered.length === 0 ? 0 : pageIndex * perPage + 1;
  const last = Math.min(filtered.length, (pageIndex + 1) * perPage);
  const hasMoney = columns.some((c) => c.money);

  return (
    <div className="data-table">
      <div className="table-tools">
        <label className="page-size">
          {t("table.show")}
          <select
            value={String(size)}
            onChange={(e) => {
              setSize(e.target.value === "all" ? "all" : Number(e.target.value));
              setPage(0);
            }}
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
            <option value="all">{t("table.all")}</option>
          </select>
          {t("table.entries")}
        </label>
        {searchable && (
          <input
            type="search"
            className="table-search"
            placeholder={t("table.search")}
            aria-label={t("table.search")}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
          />
        )}
      </div>

      <div className="table-wrap">
        <table aria-label={label}>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const col = columns.find((c) => c.id === header.column.id);
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      className={col?.money ? "num" : undefined}
                      aria-sort={
                        sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined
                      }
                    >
                      {header.column.getCanSort() ? (
                        <button
                          type="button"
                          className="sort-button"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <span aria-hidden="true" className="sort-mark">
                            {sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : "↕"}
                          </span>
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="muted">
                  {emptyText ?? t("table.empty")}
                </td>
              </tr>
            ) : (
              visible.map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((cell) => {
                    const col = columns.find((c) => c.id === cell.column.id);
                    return (
                      <td key={cell.id} className={col?.money ? "num" : undefined}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
          {hasMoney && filtered.length > 0 && (
            <tfoot>
              <tr>
                {columns.map((col, i) => (
                  <td key={col.id} className={col.money ? "num" : undefined}>
                    {col.money
                      ? formatDecimal(sumDecimal(filtered.map((r) => toText(col.value(r.original)))))
                      : i === 0
                        ? t("table.total")
                        : ""}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <div className="table-footer">
        <span>{t("table.showing", { first, last, total: filtered.length })}</span>
        <div className="pager">
          <button
            type="button"
            className="secondary small"
            disabled={!table.getCanPreviousPage()}
            onClick={() => setPage(pageIndex - 1)}
          >
            {t("table.previous")}
          </button>
          <span className="page-number">{pageIndex + 1}</span>
          <button
            type="button"
            className="secondary small"
            disabled={!table.getCanNextPage()}
            onClick={() => setPage(pageIndex + 1)}
          >
            {t("table.next")}
          </button>
        </div>
      </div>
    </div>
  );
}

function toText(value: unknown): string | null {
  return value === null || value === undefined || value === "" ? null : String(value);
}

function compareDecimal(a: string, b: string): number {
  a = a || "0";
  b = b || "0";
  const diff = sumDecimal([a, b.startsWith("-") ? b.slice(1) : `-${b}`]);
  return diff.startsWith("-") ? -1 : /[1-9]/.test(diff) ? 1 : 0;
}
