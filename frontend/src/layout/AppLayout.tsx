import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation, useNavigate, useOutletContext } from "react-router";

import { signOut, type CurrentUser } from "../api/auth";
import { visibleMenu } from "./menu";

/** Pages inside the layout read the signed-in user from here. */
export function useMe(): CurrentUser {
  return useOutletContext<CurrentUser>();
}

export default function AppLayout({ user }: { user: CurrentUser }) {
  const { t } = useTranslation();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const sections = visibleMenu(user.access);

  // On a phone the menu covers the page; close it after choosing a page.
  useEffect(() => setMenuOpen(false), [location.pathname]);

  return (
    <div className={`app ${menuOpen ? "menu-open" : ""}`}>
      <header className="topbar">
        <button
          type="button"
          className="icon-button menu-toggle"
          aria-label={t("layout.menu")}
          aria-expanded={menuOpen}
          aria-controls="side-menu"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span aria-hidden="true">☰</span>
        </button>
        <Link to="/" className="brand">
          {t("app.name")}
        </Link>
        <div className="topbar-right">
          <button type="button" className="icon-button" aria-label={t("layout.notifications")}>
            <span aria-hidden="true">🔔</span>
          </button>
          <UserMenu user={user} />
        </div>
      </header>

      <nav id="side-menu" className="sidebar" aria-label={t("layout.mainMenu")}>
        <div className="sidebar-user">
          <strong>{t("layout.welcome", { name: user.full_name })}</strong>
        </div>
        {sections.map((section) => (
          <div key={section.label} className="menu-section">
            <h2>{t(section.label)}</h2>
            <ul>
              {section.items.map((item) => (
                <li key={item.path}>
                  <NavLink to={item.path} end={item.path === "/"}>
                    {t(item.label)}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      {menuOpen && (
        <button
          type="button"
          className="scrim"
          aria-label={t("layout.closeMenu")}
          onClick={() => setMenuOpen(false)}
        />
      )}

      <div className="content">
        <Outlet context={user} />
      </div>
    </div>
  );
}

function UserMenu({ user }: { user: CurrentUser }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  async function handleSignOut() {
    await signOut().catch(() => undefined);
    queryClient.clear();
    navigate("/login", { replace: true });
  }

  return (
    <div className="user-menu" ref={box}>
      <button
        type="button"
        className="user-button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="avatar" aria-hidden="true">
          {user.full_name.slice(0, 1).toUpperCase()}
        </span>
        <span className="user-name">{user.full_name}</span>
      </button>
      {open && (
        <div className="user-dropdown" role="menu">
          <p className="muted">{user.email}</p>
          <Link role="menuitem" to="/account/password" onClick={() => setOpen(false)}>
            {t("layout.changePassword")}
          </Link>
          <button type="button" role="menuitem" className="link-button" onClick={handleSignOut}>
            {t("home.signOut")}
          </button>
        </div>
      )}
    </div>
  );
}
