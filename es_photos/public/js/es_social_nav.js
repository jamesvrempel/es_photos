/* ES Photos: make sure the ES Social top nav has a "Gallery" link and mark it
   active inside the gallery. ES Social >= 0.9.7 renders the link itself from
   the es_social_nav_links hook; on older versions this adds it. */
(function () {
  function run() {
    var nav = document.querySelector(".es-social .es-nav");
    if (!nav) return;
    var a = nav.querySelector('a[href="/social/gallery"]');
    if (!a) {
      a = document.createElement("a");
      a.href = "/social/gallery";
      a.textContent = "Gallery";
      var after = nav.querySelector('a[href="/social/pages"]') || nav.querySelector('a[href="/social/groups"]') ||
        nav.querySelector('a[href="/social"]');
      if (after) nav.insertBefore(a, after.nextSibling);
      else nav.appendChild(a);
    }
    a.setAttribute("data-esp-gallery", "1");
    if (location.pathname.indexOf("/social/gallery") === 0) a.classList.add("active");
  }
  if (document.readyState !== "loading") run();
  else document.addEventListener("DOMContentLoaded", run);
})();
