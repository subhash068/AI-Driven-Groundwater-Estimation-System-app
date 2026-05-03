import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "leaflet/dist/leaflet.css";
import "./tailwind.css";
import "./styles.css";

function getRoute(pathname) {
  if (pathname.startsWith("/dashboard")) return "/dashboard";
  if (pathname.startsWith("/forecasts")) return "/forecasts";
  if (pathname.startsWith("/anomalies")) return "/anomalies";
  if (pathname.startsWith("/recharge")) return "/recharge";
  if (pathname.startsWith("/simulation")) return "/simulation";
  if (pathname.startsWith("/validation")) return "/validation";
  if (pathname.startsWith("/explainability")) return "/explainability";
  if (pathname.startsWith("/methodology")) return "/methodology";
  if (pathname === "/" || pathname === "") return "/";
  return "/";
}

function AppShell() {
  const [pathname, setPathname] = React.useState(() => {
    if (typeof window === "undefined") return "/";
    return getRoute(window.location.pathname);
  });

  React.useEffect(() => {
    const canonical = getRoute(window.location.pathname);
    if (window.location.pathname !== canonical) {
      window.history.replaceState({}, "", canonical);
      setPathname(canonical);
    }

    const handlePopState = () => {
      const nextPath = getRoute(window.location.pathname);
      if (window.location.pathname !== nextPath) {
        window.history.replaceState({}, "", nextPath);
      }
      setPathname(nextPath);
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = React.useCallback((to, { replace = false } = {}) => {
    const nextPath = getRoute(to);
    if (nextPath === pathname) return;

    if (replace) {
      window.history.replaceState({}, "", nextPath);
    } else {
      window.history.pushState({}, "", nextPath);
    }
    setPathname(nextPath);
  }, [pathname]);

  return <App navigate={navigate} pathname={pathname} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AppShell />
  </React.StrictMode>
);

