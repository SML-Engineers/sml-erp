import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { bellKey, getBell, markRead, type NotificationItem } from "../api/notifications";
import { formatDateTime } from "../lib/time";

const REFRESH_MS = 60_000;

/** The bell in the top bar: unread count, the latest notifications, mark as read. */
export default function NotificationBell() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const bell = useQuery({ queryKey: bellKey, queryFn: getBell, refetchInterval: REFRESH_MS });
  const read = useMutation({
    mutationFn: (ids?: number[]) => markRead(ids),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: bellKey }),
  });
  const unread = bell.data?.unread ?? 0;

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  function openItem(item: NotificationItem) {
    if (!item.read) read.mutate([item.id]);
    setOpen(false);
    if (item.link) navigate(item.link);
  }

  return (
    <div className="bell" ref={box}>
      <button
        type="button"
        className="icon-button"
        aria-label={unread ? t("bell.labelUnread", { n: String(unread) }) : t("layout.notifications")}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true">🔔</span>
        {unread > 0 && (
          <span className="bell-count" aria-hidden="true">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label={t("layout.notifications")}>
          <div className="bell-head">
            <strong>{t("layout.notifications")}</strong>
            {unread > 0 && (
              <button type="button" className="link-button" onClick={() => read.mutate(undefined)}>
                {t("bell.markAll")}
              </button>
            )}
          </div>
          {bell.data && bell.data.items.length === 0 && <p className="muted">{t("bell.none")}</p>}
          <ul>
            {bell.data?.items.map((item) => (
              <li key={item.id} className={item.read ? "read" : "unread"}>
                <button type="button" className="link-button" onClick={() => openItem(item)}>
                  {item.title}
                </button>
                {item.body && <span className="muted">{item.body}</span>}
                <time className="muted" dateTime={item.created_at}>
                  {formatDateTime(item.created_at)}
                </time>
              </li>
            ))}
          </ul>
          <Link to="/account/notifications" onClick={() => setOpen(false)}>
            {t("bell.settings")}
          </Link>
        </div>
      )}
    </div>
  );
}
