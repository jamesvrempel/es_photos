/* ES Photos — gallery behaviour (no framework, matches ES Social's approach). */
(function () {
  "use strict";
  var CFG = window.ESP_CFG || {};
  var root = document.querySelector(".esp");
  if (!root) return;

  // ------------------------------------------------------------------ helpers
  function $(sel, el) { return (el || document).querySelector(sel); }
  function $$(sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function errMsg(data, fallback) {
    try {
      if (data && data._server_messages) {
        var m = JSON.parse(JSON.parse(data._server_messages)[0]);
        return (m.message || "").replace(/<[^>]+>/g, "");
      }
      if (data && data.exception) return String(data.exception).split(":").slice(1).join(":").trim() || fallback;
    } catch (e) { /* ignore */ }
    return fallback || "Something went wrong.";
  }
  function call(method, args, opts) {
    opts = opts || {};
    var body = new URLSearchParams();
    Object.keys(args || {}).forEach(function (k) { if (args[k] != null) body.append(k, args[k]); });
    return fetch("/api/method/es_photos.api." + method, {
      method: opts.get ? "GET" : "POST",
      headers: {
        "Accept": "application/json",
        "X-Frappe-CSRF-Token": CFG.csrf || "",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: opts.get ? undefined : body.toString(),
      credentials: "same-origin",
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) throw new Error(errMsg(data, r.status === 403 ? "Please log in first." : "Request failed."));
        return data.message;
      });
    });
  }
  function get(method, args) {
    var qs = new URLSearchParams(args || {}).toString();
    return fetch("/api/method/es_photos.api." + method + (qs ? "?" + qs : ""), {
      headers: { Accept: "application/json" }, credentials: "same-origin",
    }).then(function (r) { return r.json(); }).then(function (d) { return d.message; });
  }
  function toast(html, ms) {
    var t = document.createElement("div");
    t.className = "esp-toast"; t.innerHTML = html;
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, ms || 3500);
  }
  function needLogin() {
    if (!CFG.is_guest) return false;
    location.href = CFG.login_url || "/login";
    return true;
  }
  function store(k, v) {
    try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; }
  }

  // ------------------------------------------------------------------ modal
  var modal = $("[data-esp-modal]"), modalBox = $("[data-esp-modal-box]");
  function openModal(nodeOrHtml) {
    modalBox.innerHTML = "";
    if (typeof nodeOrHtml === "string") modalBox.innerHTML = nodeOrHtml; else modalBox.appendChild(nodeOrHtml);
    modal.hidden = false;
    var f = modalBox.querySelector("input,textarea,select"); if (f) f.focus();
    return modalBox;
  }
  function closeModal() { modal.hidden = true; modalBox.innerHTML = ""; }
  if (modal) {
    modal.addEventListener("click", function (e) {
      if (e.target === modal || e.target.closest("[data-esp-close]")) closeModal();
    });
  }
  function fromTemplate(id) {
    var t = document.getElementById(id);
    return t ? t.content.cloneNode(true) : null;
  }
  function wirePrivacy(scope) {
    var sel = scope.querySelector("[data-esp-privacy]"), grp = scope.querySelector("[data-esp-group-field]");
    if (!sel || !grp) return;
    var sync = function () { grp.hidden = sel.value !== "Group"; };
    sel.addEventListener("change", sync); sync();
  }
  function formData(form) {
    var o = {};
    new FormData(form).forEach(function (v, k) { o[k] = v; });
    return o;
  }

  // ------------------------------------------------------------------ layout toggle + sort
  var layout = store("esp-layout") || "grid";
  function setLayout(l) {
    root.setAttribute("data-layout", l);
    $$("[data-esp-layout]").forEach(function (b) { b.classList.toggle("active", b.dataset.espLayout === l); });
    store("esp-layout", l);
  }
  setLayout(layout);
  $$("[data-esp-layout]").forEach(function (b) {
    b.addEventListener("click", function () { setLayout(b.dataset.espLayout); });
  });
  $$("[data-esp-asort]").forEach(function (s) {
    s.addEventListener("change", function () {
      var u = new URL(location.href);
      if (s.value && s.value !== s.dataset.default) u.searchParams.set("asort", s.value); else u.searchParams.delete("asort");
      location.href = u.toString();
    });
  });
  $$("[data-esp-sort]").forEach(function (s) {
    s.addEventListener("change", function () {
      var u = new URL(location.href);
      if (s.value) u.searchParams.set("sort", s.value); else u.searchParams.delete("sort");
      u.searchParams.delete("page");
      location.href = u.toString();
    });
  });

  // ------------------------------------------------------------------ viewer / slideshow
  var viewer = $("[data-esp-viewer]");
  var V = { items: [], i: 0, timer: null, playing: false, interval: 5000 };

  // ---- slideshow speed: site default (ES Photos Settings), visitor's choice remembered in this browser
  var SPEED_KEY = "esp_slideshow_seconds";
  var SPEEDS = [1, 2, 3, 4, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120];
  function clampSecs(n) { n = parseInt(n, 10); return isNaN(n) ? 0 : Math.min(120, Math.max(1, n)); }
  function savedSecs() { try { return clampSecs(localStorage.getItem(SPEED_KEY)); } catch (e) { return 0; } }
  function setSpeed(secs, remember) {
    secs = clampSecs(secs) || 5;
    V.interval = secs * 1000;
    if (viewer) viewer.style.setProperty("--esp-interval", secs + "s");
    var sel = $("[data-esp-v-speed]");
    if (sel) {
      if (SPEEDS.indexOf(secs) < 0) {   // a custom site default that isn't in the list
        var o = document.createElement("option"); o.value = secs; o.textContent = secs + " s";
        sel.appendChild(o);
        Array.prototype.slice.call(sel.options).sort(function (a, b) { return a.value - b.value; })
          .forEach(function (x) { sel.appendChild(x); });
      }
      sel.value = String(secs);
    }
    if (remember) { try { localStorage.setItem(SPEED_KEY, String(secs)); } catch (e) { /* private mode */ } }
    if (V.playing) vRestartTimer();
  }
  function stepSpeed(dir) {
    var cur = V.interval / 1000, i;
    if (dir > 0) { for (i = 0; i < SPEEDS.length; i++) if (SPEEDS[i] > cur) return setSpeed(SPEEDS[i], true); }
    else { for (i = SPEEDS.length - 1; i >= 0; i--) if (SPEEDS[i] < cur) return setSpeed(SPEEDS[i], true); }
  }

  function vShow(i) {
    if (!V.items.length) return;
    V.i = (i + V.items.length) % V.items.length;
    var it = V.items[V.i], stage = $("[data-esp-v-stage]");
    if (it.video) {
      var m = it.video.match(/(?:v=|youtu\.be\/|embed\/|shorts\/)([A-Za-z0-9_-]{11})/);
      var vm = it.video.match(/vimeo\.com\/(?:video\/)?(\d+)/);
      var src = m ? "https://www.youtube-nocookie.com/embed/" + m[1] + "?autoplay=1&rel=0"
        : vm ? "https://player.vimeo.com/video/" + vm[1] + "?autoplay=1" : "";
      stage.innerHTML = '<iframe src="' + esc(src) + '" allow="autoplay; fullscreen; encrypted-media" allowfullscreen></iframe>';
      vPause();
    } else {
      stage.innerHTML = '<img src="' + esc(it.src) + '" alt="' + esc(it.title) + '">';
      // preload neighbour
      var n = V.items[(V.i + 1) % V.items.length];
      if (n && n.src && !n.video) { var im = new Image(); im.src = n.src; }
    }
    $("[data-esp-v-title]").textContent = it.title || "";
    $("[data-esp-v-count]").textContent = (V.i + 1) + " / " + V.items.length;
    $("[data-esp-v-link]").href = it.href + (CFG.album ? "?album=" + encodeURIComponent(CFG.album) : "");
    if (V.playing) vRestartTimer();
  }
  function vRestartTimer() {
    clearTimeout(V.timer);
    viewer.style.setProperty("--esp-interval", V.interval / 1000 + "s");
    var bar = $("[data-esp-v-progress]");
    viewer.classList.remove("playing"); void bar.offsetWidth; viewer.classList.add("playing");
    V.timer = setTimeout(function () { vShow(V.i + 1); }, V.interval);
  }
  function vPlay() { V.playing = true; vRestartTimer(); }
  function vPause() { V.playing = false; clearTimeout(V.timer); viewer.classList.remove("playing"); }
  function vOpen(items, start, play) {
    if (!items || !items.length) return;
    V.items = items; viewer.hidden = false;
    document.documentElement.style.overflow = "hidden";
    vShow(start || 0);
    if (play) vPlay(); else vPause();
    if (viewer.requestFullscreen && play) viewer.requestFullscreen().catch(function () {});
  }
  function vClose() {
    vPause(); viewer.hidden = true; $("[data-esp-v-stage]").innerHTML = "";
    document.documentElement.style.overflow = "";
    if (document.fullscreenElement) document.exitFullscreen().catch(function () {});
  }
  if (viewer) {
    var speedSel = $("[data-esp-v-speed]");
    if (speedSel) {
      SPEEDS.forEach(function (n) {
        var o = document.createElement("option"); o.value = n; o.textContent = n + " s"; speedSel.appendChild(o);
      });
      // blur afterwards so ← → space Esc keep driving the viewer
      speedSel.addEventListener("change", function () { setSpeed(speedSel.value, true); speedSel.blur(); });
    }
    setSpeed(savedSecs() || CFG.slideshow_seconds || 5, false);
    $("[data-esp-v-prev]").addEventListener("click", function () { vShow(V.i - 1); });
    $("[data-esp-v-next]").addEventListener("click", function () { vShow(V.i + 1); });
    $("[data-esp-v-close]").addEventListener("click", vClose);
    $("[data-esp-v-play]").addEventListener("click", function () { V.playing ? vPause() : vPlay(); });
    $("[data-esp-v-stage]").addEventListener("click", function (e) { if (e.target.tagName === "IMG") vShow(V.i + 1); });
    var tx = null;
    viewer.addEventListener("touchstart", function (e) { tx = e.touches[0].clientX; }, { passive: true });
    viewer.addEventListener("touchend", function (e) {
      if (tx == null) return;
      var dx = e.changedTouches[0].clientX - tx; tx = null;
      if (Math.abs(dx) > 50) vShow(V.i + (dx < 0 ? 1 : -1));
    });
  }

  function loadSlides() {
    var args = {};
    if (CFG.album) args.album = CFG.album;
    else if (CFG.keyword) args.keyword = CFG.keyword;
    if (CFG.sort) args.sort = CFG.sort;
    if (!args.album && !args.keyword) {
      // list pages (recent, random, …): use the tiles on screen
      return Promise.resolve($$(".esp-tile").map(function (t) {
        var img = t.querySelector("img");
        return { name: t.dataset.name, title: t.title, src: img ? img.src : "", href: t.getAttribute("href").split("?")[0],
          video: t.classList.contains("esp-tile-video") ? null : null };
      }));
    }
    return get("slideshow", args);
  }
  $$("[data-esp-slideshow]").forEach(function (b) {
    b.addEventListener("click", function () {
      b.disabled = true;
      loadSlides().then(function (items) {
        b.disabled = false;
        var start = 0;
        if (CFG.photo) items.forEach(function (it, i) { if (it.name === CFG.photo) start = i; });
        vOpen(items, start, true);
      }).catch(function () { b.disabled = false; });
    });
  });
  $$("[data-esp-fullscreen], [data-esp-open]").forEach(function (b) {
    b.addEventListener("click", function () {
      loadSlides().then(function (items) {
        var start = 0;
        items.forEach(function (it, i) { if (it.name === CFG.photo) start = i; });
        if (!items.length) {
          var img = $(".esp-main-img");
          items = [{ name: CFG.photo, title: document.title, src: img.currentSrc || img.src, href: location.pathname }];
        }
        vOpen(items, start, false);
      });
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.target.closest("input,textarea,select,[contenteditable]")) return;
    if (viewer && !viewer.hidden) {
      if (e.key === "ArrowRight") vShow(V.i + 1);
      else if (e.key === "ArrowLeft") vShow(V.i - 1);
      else if (e.key === "Escape") vClose();
      else if (e.key === " ") { e.preventDefault(); V.playing ? vPause() : vPlay(); }
      else if (e.key === "+" || e.key === "=") stepSpeed(1);   // slower
      else if (e.key === "-" || e.key === "_") stepSpeed(-1);  // faster
      return;
    }
    if (modal && !modal.hidden) { if (e.key === "Escape") closeModal(); return; }
    var a = e.key === "ArrowRight" ? $("[data-esp-next]") : e.key === "ArrowLeft" ? $("[data-esp-prev]") : null;
    if (a) location.href = a.href;
  });

  // ------------------------------------------------------------------ reactions
  var bar = $("[data-esp-reactbar]");
  if (bar) {
    var btn = $(".esp-react-btn", bar);
    var apply = function (r) {
      var mine = r.mine;
      btn.classList.toggle("active", !!mine);
      btn.dataset.espReact = mine || "Like";
      $("[data-esp-react-emoji]", bar).textContent = r.mine_emoji || "👍";
      $("[data-esp-react-label]", bar).textContent = mine || "Like";
      $("[data-esp-react-summary]", bar).textContent = r.total ? r.top.join("") + " " + r.total : "";
    };
    var send = function (type) {
      if (needLogin()) return;
      call("react", { photo: CFG.photo, reaction_type: type }).then(apply).catch(function (e) { toast(esc(e.message)); });
    };
    btn.addEventListener("click", function () {
      send(btn.classList.contains("active") ? btn.dataset.espReact : "Like");
    });
    $$("[data-esp-pick]", bar).forEach(function (p) {
      p.addEventListener("click", function () { send(p.dataset.espPick); });
    });
  }

  // ------------------------------------------------------------------ comments
  var list = $("[data-esp-comment-list]");
  function avatarHtml(c) {
    return c.author_image
      ? '<img class="esp-avatar" src="' + esc(c.author_image) + '" width="30" height="30" alt="">'
      : '<span class="esp-avatar esp-avatar-initials" style="width:30px;height:30px">' + esc(c.author_initials) + "</span>";
  }
  function commentHtml(c) {
    return '<div class="esp-comment" data-name="' + esc(c.name) + '"><a href="' + esc(c.author_url) + '">' + avatarHtml(c) +
      '</a><div class="esp-comment-body"><div><a class="esp-comment-author" href="' + esc(c.author_url) + '">' +
      esc(c.author_name) + '</a> <span class="es-muted">' + esc(c.when) + (c.pending ? " · awaiting review" : "") +
      '</span></div><div class="esp-comment-text">' + c.content + "</div>" +
      (c.can_delete ? '<button type="button" class="es-btn-link" data-esp-del-comment="' + esc(c.name) + '">Delete</button>' : "") +
      "</div></div>";
  }
  var cform = $("[data-esp-comment-form]");
  if (cform) {
    var ta = cform.querySelector("textarea");
    ta.addEventListener("input", function () { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 160) + "px"; });
    ta.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); cform.requestSubmit(); }
    });
    cform.addEventListener("submit", function (e) {
      e.preventDefault();
      var content = ta.value.trim(); if (!content) return;
      var b = cform.querySelector("button"); b.disabled = true;
      call("add_comment", { photo: CFG.photo, content: content }).then(function (c) {
        list.insertAdjacentHTML("beforeend", commentHtml(c));
        ta.value = ""; ta.style.height = "";
        var n = $("[data-esp-comment-count]"); if (n) n.textContent = list.children.length;
        if (c.pending) toast("Your comment is awaiting review.");
      }).catch(function (err) { toast(esc(err.message)); }).finally(function () { b.disabled = false; });
    });
  }
  if (list) {
    list.addEventListener("click", function (e) {
      var d = e.target.closest("[data-esp-del-comment]"); if (!d) return;
      if (!confirm("Delete this comment?")) return;
      call("delete_comment", { name: d.dataset.espDelComment }).then(function () {
        var el = d.closest(".esp-comment"); if (el) el.remove();
      }).catch(function (err) { toast(esc(err.message)); });
    });
  }

  // ------------------------------------------------------------------ share / post to feed
  function feedDialog(title, onSend) {
    var box = openModal(
      '<div class="es-card-title">' + esc(title) + '</div><form class="esp-form">' +
      '<label>Say something (optional)<textarea name="message" rows="3" maxlength="2000"></textarea></label>' +
      '<div class="esp-form-actions"><button type="button" class="es-btn" data-esp-close>Cancel</button>' +
      '<button class="es-btn es-btn-primary">Post</button></div></form>'
    );
    box.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var b = e.target.querySelector(".es-btn-primary"); b.disabled = true;
      onSend(e.target.message.value).then(function (r) {
        closeModal();
        toast('Posted to your feed. <a href="' + esc(r.feed_url || "/social") + '">View</a>', 6000);
      }).catch(function (err) { b.disabled = false; toast(esc(err.message)); });
    });
  }
  var shareBtn = $("[data-esp-share]");
  if (shareBtn) shareBtn.addEventListener("click", function () {
    if (needLogin()) return;
    feedDialog("Share this photo to the ES Social feed", function (msg) {
      return call("share_to_feed", { photo: CFG.photo, message: msg });
    });
  });
  var postAlbumBtn = $("[data-esp-post-album]");
  if (postAlbumBtn) postAlbumBtn.addEventListener("click", function () {
    feedDialog("Post this album to the ES Social feed", function (msg) {
      return call("post_album_to_feed", { album: CFG.album, message: msg }).then(function (r) {
        postAlbumBtn.remove(); return r;
      });
    });
  });

  // ------------------------------------------------------------------ album edit
  var editAlbum = $("[data-esp-edit-album]");
  if (editAlbum) editAlbum.addEventListener("click", function () {
    var box = openModal(fromTemplate("esp-album-form-tpl"));
    wirePrivacy(box);
    box.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      call("save_album", formData(e.target)).then(function (r) { location.href = r.url; })
        .catch(function (err) { toast(esc(err.message)); });
    });
  });

  // ------------------------------------------------------------------ photo owner tools
  var editPhoto = $("[data-esp-edit-photo]");
  if (editPhoto) editPhoto.addEventListener("click", function () {
    var box = openModal(fromTemplate("esp-photo-form-tpl"));
    box.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var d = formData(e.target); d.name = CFG.photo;
      call("update_photo", d).then(function () { location.reload(); }).catch(function (err) { toast(esc(err.message)); });
    });
  });
  var coverBtn = $("[data-esp-cover]");
  if (coverBtn) coverBtn.addEventListener("click", function () {
    call("set_cover", { album: CFG.album, photo: CFG.photo }).then(function () { toast("Album cover updated."); })
      .catch(function (err) { toast(esc(err.message)); });
  });
  var delBtn = $("[data-esp-delete-photo]");
  if (delBtn) delBtn.addEventListener("click", function () {
    if (!confirm("Delete this photo? This can't be undone.")) return;
    call("delete_photo", { name: CFG.photo }).then(function (r) { location.href = r.album_url; })
      .catch(function (err) { toast(esc(err.message)); });
  });

  // ------------------------------------------------------------------ upload
  var up = $("[data-esp-upload]");
  if (up) initUpload(up);

  function initUpload(up) {
    var albumSel = $("[data-esp-upload-album]", up), newBox = $("[data-esp-new-album]", up);
    var drop = $("[data-esp-drop]", up), input = $("[data-esp-file]", up), queue = $("[data-esp-queue]", up);
    var done = $("[data-esp-upload-done]", up);
    var albumName = albumSel.value || null, uploaded = 0, active = 0, pending = [];
    wirePrivacy(newBox);
    albumSel.addEventListener("change", function () { albumName = albumSel.value || null; newBox.hidden = !!albumName; });

    function ensureAlbum() {
      if (albumName) return Promise.resolve(albumName);
      var d = {};
      $$("input,select,textarea", newBox).forEach(function (el) { d[el.name] = el.value; });
      if (!d.title || !d.title.trim()) {
        return Promise.reject(new Error("Give the new album a title first."));
      }
      return call("save_album", d).then(function (r) {
        albumName = r.name;
        var o = document.createElement("option"); o.value = r.name; o.textContent = d.title; o.selected = true;
        albumSel.appendChild(o); newBox.hidden = true;
        return albumName;
      });
    }

    var PHOTO_EXT = /\.(jpe?g|png|webp|gif|tiff?|bmp|heic|heif)$/i;
    var maxBytes = (CFG.max_mb || 0) * 1048576;
    var failed = 0, skippedDup = 0;

    var PARALLEL = 2;              // uploads at a time
    var TIMEOUT_MS = 10 * 60000;   // give up on one photo after 10 minutes without an answer
    var RETRY_STATUS = [0, 502, 503, 504, 520, 522, 524];

    function fail(job, msg, final) {
      failed++;
      job.failed = !final;           // a retryable failure: tapping the photo tries again
      job.el.classList.add("err");
      job.el.classList.toggle("retry", !final);
      job.el.querySelector(".esp-q-state").textContent = final ? "failed" : "↻ retry";
      var m = job.el.querySelector(".esp-q-msg");
      m.textContent = msg; m.hidden = false;
      job.el.title = job.file.name + ": " + msg;
    }

    function retry(job) {
      if (!job.failed) return;
      failed--; job.failed = false; job.tries = 0;
      job.el.classList.remove("err", "retry");
      job.el.querySelector(".esp-q-msg").hidden = true;
      job.el.querySelector(".esp-q-state").textContent = "waiting";
      job.el.querySelector(".esp-q-bar").style.width = "0";
      done.hidden = true;
      pending.push(job); pump();
    }

    function addFiles(files) {
      var all = Array.prototype.slice.call(files);
      // some phones / cloud folders report no type, so accept by extension too
      files = all.filter(function (f) { return /^image\//.test(f.type) || PHOTO_EXT.test(f.name); });
      var skipped = all.length - files.length;
      if (skipped) toast(skipped + (skipped === 1 ? " file isn't" : " files aren't") + " a photo and " + (skipped === 1 ? "was" : "were") + " skipped.");
      if (!files.length) return;
      ensureAlbum().then(function () {
        files.forEach(function (f) {
          var el = document.createElement("div");
          el.className = "esp-q";
          // No full-size preview: decoding dozens of 20–40 MP camera files in the page
          // freezes the browser. The name shows until the server's thumbnail arrives.
          el.innerHTML = '<img alt="" hidden><span class="esp-q-name"></span><span class="esp-q-state">waiting</span>' +
            '<i class="esp-q-bar"></i><span class="esp-q-msg" hidden></span>';
          el.querySelector(".esp-q-name").textContent = f.name + " · " + (f.size / 1048576).toFixed(1) + " MB";
          queue.appendChild(el);
          var job = { file: f, el: el, tries: 0 };
          el.addEventListener("click", function () { retry(job); });
          if (maxBytes && f.size > maxBytes) {
            fail(job, "Too large: " + (f.size / 1048576).toFixed(1) + " MB (limit " + CFG.max_mb + " MB)", true);
            return;
          }
          pending.push(job);
        });
        pump();
      }).catch(function (err) { toast(esc(err.message)); });
    }

    function httpMsg(xhr, data) {
      if (xhr.status === 413) return "Too large for the server — raise max_file_size in the site config (and nginx client_max_body_size)";
      if (xhr.status === 403) return errMsg(data, "Not allowed — your session may have expired; reload the page");
      if (xhr.status === 0) return "Connection lost during upload — tap to try again";
      if ([502, 503, 504, 520, 522, 524].indexOf(xhr.status) >= 0)
        return "The server didn't answer in time (HTTP " + xhr.status + ") — tap to try again";
      if (xhr.status >= 500) return errMsg(data, "Server error " + xhr.status + " — see Error Log in the desk");
      return errMsg(data, "Upload failed (HTTP " + xhr.status + ")");
    }

    function pump() {
      while (active < PARALLEL && pending.length) send(pending.shift());
      if (!active && !pending.length && failed) {
        toast(failed + " photo" + (failed === 1 ? "" : "s") + " couldn't be uploaded — the reason is shown on each red one.");
      }
      if (!active && !pending.length && (uploaded || skippedDup)) {
        done.hidden = false;
        done.innerHTML = "✅ " + uploaded + " photo" + (uploaded === 1 ? "" : "s") + " uploaded" +
          (skippedDup ? " · " + skippedDup + " already in this album (skipped)" : "") + '. <a href="' +
          esc(CFG.base + "/album/" + albumName) + '"><b>Open the album →</b></a>';
      }
    }

    function send(job) {
      active++;
      job.tries++;
      var fd = new FormData();
      fd.append("file", job.file, job.file.name);
      fd.append("album", albumName);
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/method/es_photos.api.upload_photo");
      xhr.setRequestHeader("X-Frappe-CSRF-Token", CFG.csrf || "");
      xhr.setRequestHeader("Accept", "application/json");
      var state = job.el.querySelector(".esp-q-state"), barEl = job.el.querySelector(".esp-q-bar");
      xhr.timeout = TIMEOUT_MS;
      state.textContent = job.tries > 1 ? "retrying" : "uploading";
      xhr.upload.onprogress = function (e) {
        if (!e.lengthComputable) return;
        var pct = e.loaded / e.total * 100;
        barEl.style.width = pct + "%";
        state.textContent = pct >= 100 ? "processing…" : Math.floor(pct) + "%";
      };
      var finished = false;
      function finish(ok, msg) {
        if (finished) return; finished = true;
        active--;
        if (ok && ok.duplicate) {
          skippedDup++; state.textContent = "already in this album"; barEl.style.width = "100%";
          job.el.classList.add("dup");
          var dimg = job.el.querySelector("img");
          if (ok.thumb) { dimg.src = ok.thumb; dimg.hidden = false; }
        } else if (ok) {
          uploaded++; state.textContent = "✓"; barEl.style.width = "100%";
          var img = job.el.querySelector("img");
          if (ok.thumb) { img.src = ok.thumb; img.hidden = false; }
        } else if (job.tries < 2 && RETRY_STATUS.indexOf(xhr.status) >= 0) {
          pending.unshift(job);       // one automatic retry for dropped connections / timeouts
        } else {
          fail(job, msg);
        }
        pump();
      }
      xhr.onload = function () {
        var data = {}; try { data = JSON.parse(xhr.responseText); } catch (e) { /* ignore */ }
        if (xhr.status === 200 && data.message) finish(data.message);
        else finish(null, httpMsg(xhr, data));
      };
      xhr.onerror = function () { finish(null, httpMsg(xhr, {})); };
      xhr.onabort = function () { finish(null, "Upload stopped — tap to try again"); };
      xhr.ontimeout = function () { finish(null, "No answer from the server after 10 minutes — tap to try again"); };
      xhr.send(fd);
    }

    drop.addEventListener("click", function () { input.click(); });
    drop.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    input.addEventListener("change", function () { addFiles(input.files); input.value = ""; });
    ["dragenter", "dragover"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("over"); });
    });
    drop.addEventListener("drop", function (e) { addFiles(e.dataTransfer.files); });
    window.addEventListener("beforeunload", function (e) {
      if (active || pending.length) { e.preventDefault(); e.returnValue = ""; }
    });

    var addVideo = $("[data-esp-add-video]", up);
    if (addVideo) addVideo.addEventListener("click", function () {
      var url = $("[data-esp-video-url]", up).value.trim(), title = $("[data-esp-video-title]", up).value.trim();
      if (!url) return;
      ensureAlbum().then(function () {
        return call("add_video", { album: albumName, video_url: url, title: title });
      }).then(function (r) { location.href = r.url; }).catch(function (err) { toast(esc(err.message)); });
    });
  }
})();
