export function currentView({ hostname = "", pathname = "/" } = {}) {
  const subdomain = hostname.split(".")[0];
  if (subdomain === "extract") {
    return "extract";
  }
  if (subdomain === "library") {
    return "library";
  }
  if (pathname.startsWith("/extract")) {
    return "extract";
  }
  if (pathname.startsWith("/library")) {
    return "library";
  }
  return "home";
}
