// Minimal hash router: #/?siret=…&week=…  and  #/tender/<id>?siret=…
import { useEffect, useState } from "react";

export interface Route {
  page: "shortlist" | "tender";
  id?: string;
  params: URLSearchParams;
}

function parse(): Route {
  const raw = window.location.hash.replace(/^#/, "") || "/";
  const [path = "/", query = ""] = raw.split("?");
  const params = new URLSearchParams(query);
  const m = path.match(/^\/tender\/(.+)$/);
  return m?.[1] ? { page: "tender", id: decodeURIComponent(m[1]), params } : { page: "shortlist", params };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(path: string, params: Record<string, string | undefined> = {}) {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) s.set(k, v);
  const query = s.toString();
  window.location.hash = query ? `${path}?${query}` : path;
}
