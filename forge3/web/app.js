/* FORGE 3.0 — yellow chatbot skin over the FORGE 3.0 Forge room. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var bridge = function () { return window.pywebview && window.pywebview.api; };

  var state = null;
  var models = [];
  var backends = [];
  var sessions = [];
  var activeId = "";
  var pending = null;      // { md, body, wrap } of the live assistant turn
  var streamBuf = "";      // raw text accumulated this turn
  var phase = "idle";
  var atBottom = true;
  var lastUserText = "";
  var startedAt = 0;

  /* ───────────────────────── markdown ───────────────────────── */

  // quotes are escaped too: a model-authored link URL lands inside an attribute,
  // and a bare " there would break out of it
  function esc(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function inline(value) {
    // code spans are lifted out behind a delimiter no prose can contain, so a bare
    // number in the text ("attempt 2 of 4") is never read back as a placeholder
    var spans = [];
    var text = String(value).replace(/`([^`]+)`/g, function (_, code) {
      spans.push(code);
      return "\u0000" + (spans.length - 1) + "\u0000";
    });
    text = esc(text);
    // a link must never navigate: pywebview would replace the app window itself
    text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
      '<a href="#" data-url="$2" title="$2">$1</a>');
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    return text.replace(/\u0000(\d+)\u0000/g, function (_, index) {
      return "<code>" + esc(spans[index]) + "</code>";
    });
  }

  function codeBlock(lang, body) {
    return '<div class="codeblock"><div class="codehead"><span class="lang">' +
      esc(lang || "text") +
      '</span><button type="button" class="copycode">copy</button></div>' +
      "<pre><code>" + esc(body.replace(/\n+$/, "")) + "</code></pre></div>";
  }

  function md(source) {
    var text = String(source == null ? "" : source);
    // a fence still open mid-stream is closed for rendering only, so the block
    // forms as it arrives instead of snapping into shape on complete
    if ((text.split("```").length - 1) % 2 === 1) text += "\n```";

    var lines = text.split("\n");
    var out = [];
    var i = 0;

    while (i < lines.length) {
      var line = lines[i];

      if (/^```/.test(line)) {
        var lang = line.slice(3).trim();
        var buf = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++; }
        i++;
        out.push(codeBlock(lang, buf.join("\n")));
        continue;
      }

      if (/^\s*$/.test(line)) { i++; continue; }

      if (/^---+\s*$/.test(line)) { out.push("<hr>"); i++; continue; }

      var heading = /^(#{1,4})\s+(.*)$/.exec(line);
      if (heading) {
        var tag = heading[1].length <= 2 ? "h3" : "h4";
        out.push("<" + tag + ">" + inline(heading[2]) + "</" + tag + ">");
        i++;
        continue;
      }

      if (/^\s*\|.*\|\s*$/.test(line) &&
          i + 1 < lines.length &&
          /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
        var cells = function (row) {
          return row.trim().replace(/^\||\|$/g, "").split("|").map(function (cell) {
            return cell.trim();
          });
        };
        var head = cells(line);
        i += 2;
        var rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(cells(lines[i])); i++; }
        var table = '<div class="tablewrap"><table><thead><tr>';
        head.forEach(function (cell) { table += "<th>" + inline(cell) + "</th>"; });
        table += "</tr></thead><tbody>";
        rows.forEach(function (row) {
          table += "<tr>";
          row.forEach(function (cell) { table += "<td>" + inline(cell) + "</td>"; });
          table += "</tr>";
        });
        out.push(table + "</tbody></table></div>");
        continue;
      }

      if (/^\s*>\s?/.test(line)) {
        var quote = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          quote.push(lines[i].replace(/^\s*>\s?/, ""));
          i++;
        }
        out.push("<blockquote>" + inline(quote.join(" ")) + "</blockquote>");
        continue;
      }

      if (/^\s*[-*]\s+/.test(line)) {
        var bullets = [];
        while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
          bullets.push("<li>" + inline(lines[i].replace(/^\s*[-*]\s+/, "")) + "</li>");
          i++;
        }
        out.push("<ul>" + bullets.join("") + "</ul>");
        continue;
      }

      if (/^\s*\d+[.)]\s+/.test(line)) {
        var numbered = [];
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          numbered.push("<li>" + inline(lines[i].replace(/^\s*\d+[.)]\s+/, "")) + "</li>");
          i++;
        }
        out.push("<ol>" + numbered.join("") + "</ol>");
        continue;
      }

      var para = [];
      while (i < lines.length &&
             !/^\s*$/.test(lines[i]) &&
             !/^(```|#{1,4}\s|\s*[-*]\s|\s*\d+[.)]\s|\s*>|---+\s*$)/.test(lines[i]) &&
             !/^\s*\|.*\|\s*$/.test(lines[i])) {
        para.push(lines[i]);
        i++;
      }
      // A table row whose separator row has not streamed in yet matches no
      // branch above and is barred from the paragraph run, which would leave i
      // standing still and spin this loop forever. Take the line as prose so
      // the cursor always advances; it snaps into a table once the separator
      // lands, the same way an unclosed fence is closed for rendering.
      if (!para.length) {
        para.push(lines[i]);
        i++;
      }
      out.push("<p>" + inline(para.join(" ")) + "</p>");
    }

    return out.join("");
  }

  /* ───────────────────────── chrome ───────────────────────── */

  var toastTimer = null;
  function toast(message) {
    var el = $("toast");
    el.textContent = message;
    el.classList.add("on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("on"); }, 1800);
  }

  function setAlert(text, bad) {
    var chip = $("alertChip");
    if (!text) {
      chip.hidden = true;
      return;
    }
    $("alertText").textContent = text;
    chip.classList.toggle("bad", Boolean(bad));
    chip.hidden = false;
  }

  function busy() {
    return phase !== "idle" && phase !== "ready";
  }

  function paintSendButton() {
    var button = $("sendBtn");
    if (busy()) {
      button.classList.add("stop");
      button.innerHTML = '<span class="sq"></span><span>Stop</span>';
      button.disabled = false;
      button.setAttribute("aria-label", "Stop generating");
    } else {
      button.classList.remove("stop");
      button.innerHTML =
        '<span>Send</span><svg width="12" height="12" viewBox="0 0 13 13" fill="none" ' +
        'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M6.5 10.5v-8M3 6l3.5-3.5L10 6"></path></svg>';
      button.disabled = !$("input").value.trim();
      button.setAttribute("aria-label", "Send");
    }
  }

  function setPhase(next, payload) {
    phase = next === "ready" ? "idle" : next;
    payload = payload || {};

    if (phase === "hold") {
      if (payload.fallback) setAlert("falling back");
      else if (payload.attempt && payload.maximum) setAlert("hold " + payload.attempt + "/" + payload.maximum);
      else setAlert("hold");
    } else if (phase !== "idle") {
      setAlert("");
    }

    paintSendButton();
  }

  /* ───────────────────────── thread ───────────────────────── */

  function showEmpty(on) {
    $("empty").hidden = !on;
    $("turns").hidden = on;
  }

  // The label holds still and only the dots move: a phase change that swaps
  // "thinking" for "held - attempt 2 of 4" should not make the line jump.
  function setWaiting(pane, label) {
    pane.className = "md waiting";
    pane.innerHTML =
      '<span class="think"><span class="thinkword">' + esc(label) + "</span>" +
      '<span class="dots" aria-hidden="true"><i></i><i></i><i></i></span></span>';
  }

  function nearBottom() {
    var thread = $("thread");
    return thread.scrollHeight - thread.scrollTop - thread.clientHeight < 60;
  }

  function toBottom(force) {
    if (!force && !atBottom) return;
    var thread = $("thread");
    thread.scrollTop = thread.scrollHeight;
    atBottom = true;
    $("jumpBtn").hidden = true;
  }

  function nestedCanScroll(root, from, deltaY) {
    var node = from;
    while (node && node !== root) {
      if (node.scrollHeight > node.clientHeight + 1) {
        var overflow = window.getComputedStyle(node).overflowY;
        if (overflow === "auto" || overflow === "scroll") {
          if (deltaY < 0 && node.scrollTop > 0) return true;
          if (deltaY > 0 && node.scrollTop < node.scrollHeight - node.clientHeight - 1) return true;
        }
      }
      node = node.parentNode;
    }
    return false;
  }

  function bindScroller(el) {
    if (!el || el.getAttribute("data-scroller") === "on") return;
    el.setAttribute("data-scroller", "on");
    el.addEventListener("wheel", function (event) {
      if (event.ctrlKey) return;
      if (nestedCanScroll(el, event.target, event.deltaY)) return;
      var max = el.scrollHeight - el.clientHeight;
      if (max <= 1) return;
      var delta = event.deltaY;
      if (event.deltaMode === 1) delta *= 16;
      if (event.deltaMode === 2) delta *= el.clientHeight;
      var next = el.scrollTop + delta;
      if (next < 0) next = 0;
      if (next > max) next = max;
      if (next === el.scrollTop) return;
      el.scrollTop = next;
      event.preventDefault();
    }, { passive: false });
  }

  function scrollThreadBy(amount) {
    var thread = $("thread");
    var max = thread.scrollHeight - thread.clientHeight;
    if (max <= 1) return false;
    thread.scrollTop = Math.max(0, Math.min(max, thread.scrollTop + amount));
    atBottom = nearBottom();
    $("jumpBtn").hidden = atBottom;
    return true;
  }

  function copyButton(getText) {
    var button = document.createElement("button");
    button.type = "button";
    button.innerHTML =
      '<svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4">' +
      '<rect x="3.4" y="3.4" width="6.4" height="6.4" rx="1.3"></rect>' +
      '<path d="M8.6 3.4V2.6a1.3 1.3 0 0 0-1.3-1.3H2.6a1.3 1.3 0 0 0-1.3 1.3v4.7a1.3 1.3 0 0 0 1.3 1.3h.8"></path>' +
      "</svg>copy";
    button.addEventListener("click", function () {
      var text = getText();
      if (navigator.clipboard) navigator.clipboard.writeText(text).catch(function () {});
      toast("copied");
    });
    return button;
  }

  function reuseButton(text) {
    var button = document.createElement("button");
    button.type = "button";
    button.title = "Put this back in the composer";
    button.innerHTML =
      '<svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" ' +
      'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M10 6a4 4 0 1 1-1.3-2.9"></path><path d="M10.4 1.4v2.6H7.8"></path></svg>reuse';
    button.addEventListener("click", function () {
      $("input").value = text;
      grow();
      paintSendButton();
      $("input").focus();
      toast("put back in the composer");
    });
    return button;
  }

  function metaLine(usage, seconds, held, holdClass) {
    var bits = [];
    if (seconds) bits.push(seconds.toFixed(1) + "s");
    if (usage && (usage.input || usage.output)) {
      bits.push(usage.input + " in · " + usage.output + " out");
    }
    if (held) bits.push("held" + (holdClass ? " · " + holdClass : ""));
    return bits.join("  ");
  }

  function wireCodeCopy(scope) {
    var buttons = scope.querySelectorAll(".copycode");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener("click", function (event) {
        var block = event.currentTarget.parentNode.parentNode.querySelector("code");
        if (navigator.clipboard) navigator.clipboard.writeText(block.textContent).catch(function () {});
        var button = event.currentTarget;
        button.textContent = "copied";
        setTimeout(function () { button.textContent = "copy"; }, 1200);
      });
    }
  }

  function addUserTurn(text) {
    showEmpty(false);
    lastUserText = text;

    var wrap = document.createElement("div");
    wrap.className = "turn you";

    var who = document.createElement("div");
    who.className = "who";
    who.textContent = "You";

    var bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;

    var actions = document.createElement("div");
    actions.className = "actions";
    actions.appendChild(copyButton(function () { return text; }));
    actions.appendChild(reuseButton(text));

    wrap.appendChild(who);
    wrap.appendChild(bubble);
    wrap.appendChild(actions);
    $("turns").appendChild(wrap);
    toBottom(true);
    return wrap;
  }

  function addBotTurn(text, live) {
    showEmpty(false);

    var wrap = document.createElement("div");
    wrap.className = "turn forge";
    wrap.innerHTML =
      '<div class="who">Forge</div>' +
      '<div class="bot">' +
      '<svg class="glyph" viewBox="0 0 200 200" aria-hidden="true"><use href="#forgeSword"></use></svg>' +
      '<div class="body"><div class="md"></div></div></div>';

    var body = wrap.querySelector(".body");
    var pane = wrap.querySelector(".md");

    if (live) {
      setWaiting(pane, "thinking");
    } else {
      pane.innerHTML = md(text);
      wireCodeCopy(pane);
      var actions = document.createElement("div");
      actions.className = "actions";
      actions.appendChild(copyButton(function () { return text; }));
      body.appendChild(actions);
    }

    $("turns").appendChild(wrap);
    toBottom(true);
    return { wrap: wrap, body: body, md: pane };
  }

  // Tokens arrive far faster than the screen refreshes, and each repaint
  // re-parses the whole answer and measures the scroller. Coalescing onto one
  // frame means a burst of tokens costs a single parse instead of one each.
  var paintFrame = 0;

  function cancelPaint() {
    if (!paintFrame) return;
    cancelAnimationFrame(paintFrame);
    paintFrame = 0;
  }

  function paintPending() {
    if (!pending || paintFrame) return;
    paintFrame = requestAnimationFrame(function () {
      paintFrame = 0;
      if (!pending) return;          // finished or failed while the frame waited
      if (pending.md.classList.contains("waiting")) {
        pending.md.classList.remove("waiting");
        pending.md.classList.add("streaming");
      }
      pending.md.innerHTML = md(streamBuf);
      toBottom(false);
    });
  }

  function finishPending(text, usage, held, holdClass, note) {
    cancelPaint();
    if (!pending) return;
    var final = text == null ? streamBuf : text;

    pending.md.className = "md";
    pending.md.innerHTML = md(final);
    wireCodeCopy(pending.md);

    if (note) {
      var line = document.createElement("p");
      line.className = "stopnote";
      line.textContent = note;
      pending.md.appendChild(line);
    }

    var actions = document.createElement("div");
    actions.className = "actions";
    actions.appendChild(copyButton(function () { return final; }));

    var meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = metaLine(usage, startedAt ? (Date.now() - startedAt) / 1000 : 0, held, holdClass);
    actions.appendChild(meta);

    pending.body.appendChild(actions);
    pending = null;
    streamBuf = "";
    startedAt = 0;
    toBottom(false);
  }

  function failPending(message) {
    cancelPaint();
    if (!pending) {
      setAlert(message.slice(0, 40), true);
      return;
    }
    pending.md.className = "md failed";
    pending.md.textContent = message;
    pending = null;
    streamBuf = "";
    startedAt = 0;
    setPhase("idle");
    setAlert(message.slice(0, 40), true);
  }

  function resetThread(turns) {
    cancelPaint();
    $("turns").innerHTML = "";
    pending = null;
    streamBuf = "";
    var rows = turns || [];
    showEmpty(rows.length === 0);
    rows.forEach(function (turn) {
      if (turn.role === "user") addUserTurn(turn.content || "");
      else addBotTurn(turn.content || "", false);
    });
    atBottom = true;
    toBottom(true);
  }

  /* ───────────────────────── sessions ───────────────────────── */

  function groupFor(updatedAt) {
    if (!updatedAt) return "Earlier";
    var then = new Date(updatedAt * 1000);
    var now = new Date();
    var startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    var stamp = then.getTime();
    if (stamp >= startOfToday) return "Today";
    if (stamp >= startOfToday - 86400000) return "Yesterday";
    if (stamp >= startOfToday - 7 * 86400000) return "Previous 7 days";
    return "Earlier";
  }

  var openMenu = null;

  function closeMenu() {
    if (openMenu) {
      openMenu.remove();
      openMenu = null;
    }
    var rows = document.querySelectorAll(".chatrow.menuopen");
    for (var i = 0; i < rows.length; i++) rows[i].classList.remove("menuopen");
  }

  function sessionTurns(payload) {
    if (!payload) return [];
    if (payload.draft && payload.draft.length) return payload.draft;
    return payload.chat || [];
  }

  function paintSessions() {
    var host = $("chats");
    var query = $("chatSearch").value.trim().toLowerCase();
    host.innerHTML = "";
    closeMenu();

    var order = ["Today", "Yesterday", "Previous 7 days", "Earlier"];
    var buckets = {};
    var shown = 0;

    sessions.forEach(function (item) {
      var title = item.title || "New chat";
      var preview = item.preview || "";
      if (query && (title + " " + preview).toLowerCase().indexOf(query) === -1) return;
      if (!query && !item.message_count && item.id !== activeId) return;
      var key = groupFor(item.updated_at);
      (buckets[key] = buckets[key] || []).push(item);
      shown++;
    });

    if (!shown) {
      var none = document.createElement("div");
      none.className = "grouplabel";
      none.textContent = query ? "nothing matches" : "saved chats land here after you send";
      host.appendChild(none);
      return;
    }

    order.forEach(function (key) {
      var rows = buckets[key];
      if (!rows || !rows.length) return;

      var label = document.createElement("div");
      label.className = "grouplabel";
      label.textContent = key;
      host.appendChild(label);

      rows.forEach(function (item) {
        host.appendChild(sessionRow(item));
      });
    });
  }

  function sessionRow(item) {
    var row = document.createElement("div");
    row.className = "chatrow" + (item.id === activeId ? " on" : "");

    var meta = document.createElement("div");
    meta.className = "meta";

    var title = document.createElement("span");
    title.className = "t";
    title.textContent = item.title || "New chat";
    if (item.message_count) title.title = item.message_count + " messages";
    meta.appendChild(title);

    if (item.preview && item.preview !== (item.title || "")) {
      var preview = document.createElement("span");
      preview.className = "p";
      preview.textContent = item.preview;
      preview.title = item.preview;
      meta.appendChild(preview);
    }

    var kebab = document.createElement("button");
    kebab.className = "kebab";
    kebab.type = "button";
    kebab.setAttribute("aria-label", "Chat options");
    kebab.textContent = "⋯";
    kebab.addEventListener("click", function (event) {
      event.stopPropagation();
      var wasOpen = openMenu && openMenu.dataset.owner === item.id;
      closeMenu();
      if (wasOpen) return;
      row.classList.add("menuopen");
      openMenu = buildRowMenu(item, row);
    });

    row.appendChild(meta);
    row.appendChild(kebab);
    row.addEventListener("click", function () { loadSession(item.id); });
    row.addEventListener("dblclick", function () { startRename(item, row); });

    return row;
  }

  function buildRowMenu(item, row) {
    var menu = document.createElement("div");
    menu.className = "rowmenu";
    menu.dataset.owner = item.id;

    function option(label, className, handler) {
      var button = document.createElement("button");
      button.type = "button";
      if (className) button.className = className;
      button.textContent = label;
      button.addEventListener("click", handler);
      return button;
    }

    menu.appendChild(option("Rename", "", function () {
      closeMenu();
      startRename(item, row);
    }));

    var separator = document.createElement("div");
    separator.className = "sep";
    menu.appendChild(separator);

    menu.appendChild(option("Delete chat", "danger", function () {
      menu.innerHTML = "";
      var note = document.createElement("div");
      note.className = "confirm";
      note.textContent = "encrypted history · no undo";
      menu.appendChild(note);
      menu.appendChild(option("Yes, delete it", "danger", function () {
        closeMenu();
        removeSession(item.id);
      }));
      menu.appendChild(option("Keep it", "", function () { closeMenu(); }));
    }));

    document.body.appendChild(menu);

    var rect = row.getBoundingClientRect();
    var width = menu.offsetWidth;
    var height = menu.offsetHeight;
    var left = Math.min(rect.left + 24, window.innerWidth - width - 10);
    var top = rect.bottom + 4;
    if (top + height > window.innerHeight - 10) top = Math.max(10, rect.top - height - 4);
    menu.style.left = Math.max(10, left) + "px";
    menu.style.top = top + "px";

    return menu;
  }

  function startRename(item, row) {
    var title = row.querySelector(".t");
    if (!title) return;
    var parent = title.parentNode;

    var input = document.createElement("input");
    input.className = "rename";
    input.value = item.title || "";
    parent.replaceChild(input, title);
    input.focus();
    input.select();

    var settled = false;

    function commit() {
      if (settled) return;
      settled = true;
      var next = input.value.trim();
      if (!next || next === item.title) {
        paintSessions();
        return;
      }
      bridge().rename_session(item.id, next).then(function (result) {
        if (!result || !result.ok) toast((result && result.error) || "could not rename");
        refreshSessions();
      });
    }

    input.addEventListener("click", function (event) { event.stopPropagation(); });
    input.addEventListener("dblclick", function (event) { event.stopPropagation(); });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); commit(); }
      if (event.key === "Escape") { settled = true; paintSessions(); }
    });
    input.addEventListener("blur", commit);
  }

  function removeSession(id) {
    bridge().delete_session(id).then(function (result) {
      if (!result || !result.ok) {
        toast((result && result.error) || "could not delete");
        return;
      }
      toast("chat deleted");
      refreshSessions(result.id);
    });
  }

  function loadSession(id) {
    if (id === activeId) return;
    bridge().load_session(id).then(function (result) {
      if (!result || !result.ok) {
        toast((result && result.error) || "could not load");
        return;
      }
      activeId = result.id;
      resetThread(sessionTurns(result.payload));
      paintSessions();
      paintTitle();
    }).catch(function (error) {
      toast("could not load that chat");
      if (window.console) console.error(error);
    });
  }

  function refreshSessions(preferId) {
    var api = bridge();
    if (!api) return Promise.resolve();
    return api.list_sessions().then(function (rows) {
      sessions = rows || [];
      return api.get_state();
    }).then(function (next) {
      applyState(next);
      if (preferId) activeId = preferId;
      paintSessions();
      paintTitle();
    }).catch(function (error) {
      toast("could not refresh chats");
      if (window.console) console.error(error);
    });
  }

  function paintTitle() {
    var current = null;
    for (var i = 0; i < sessions.length; i++) {
      if (sessions[i].id === activeId) { current = sessions[i]; break; }
    }
    $("titleBar").textContent = current ? (current.title || "New chat") : "";
  }

  function paintDrawer(path) {
    if (!path) return;
    $("drawerPath").textContent = path;
    $("drawerPath").title = path;
    $("setDrawer").textContent = path;
    $("setDrawer").title = path;
  }

  /* ───────────────────────── state ───────────────────────── */

  function applyState(next) {
    if (!next) return;
    state = next.state || next;
    activeId = state.session_id || activeId;

    var model = state.draft_model || "no model";
    $("modelName").textContent = model;
    $("modelProvider").textContent = state.draft_backend || "backend";
    $("modelChip").title = (state.draft_backend || "") + " · " + model;

    var locked = Boolean(state.locked);
    $("lockText").textContent = locked ? "locked" : (state.vault || "open");
    $("lockChip").classList.toggle("locked", locked);
    $("unlock").hidden = !locked;
    if (locked) setTimeout(function () { $("pass").focus(); }, 30);

    var room = state.rooms && state.rooms.forge;
    if (room && room.phase) setPhase(room.phase);

    paintSettings();
  }

  /* ───────────────────────── model picker ───────────────────────── */

  var pop = null;

  function pinModel(item, after) {
    if (!bridge()) return;
    if (!item.keyed) {
      toast("no key for " + item.backend + " — add one in Settings");
      return;
    }
    bridge().pin_model(item.backend, item.model).then(function (result) {
      if (!result || !result.ok) {
        toast((result && result.error) || "could not pin");
        return;
      }
      applyState(result.state);
      if (after) after();
      toast("pinned · forge-3 overlay only");
    });
  }

  // one row shape for the chip popover and the settings pane both, so a pin
  // made in either place reads the same
  function modelRow(item, after) {
    var row = document.createElement("div");
    var current = state && state.draft_backend === item.backend && state.draft_model === item.model;
    row.className = "mrow" + (current ? " on" : "");

    var name = document.createElement("span");
    name.className = "mid";
    name.textContent = item.model;
    row.appendChild(name);

    (item.traits || []).forEach(function (trait) {
      var tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = trait;
      row.appendChild(tag);
    });

    if (!item.keyed) {
      var nokey = document.createElement("span");
      nokey.className = "tag nokey";
      nokey.textContent = "no key";
      row.appendChild(nokey);
    }

    if (current) {
      var tick = document.createElement("span");
      tick.className = "tick";
      tick.textContent = "●";
      row.appendChild(tick);
    }

    row.addEventListener("click", function () { pinModel(item, after); });
    return row;
  }

  function paintModelList(list, query, onlyKeyed, limit, after) {
    var byBackend = {};
    var order = [];
    models.forEach(function (item) {
      if (onlyKeyed && !item.keyed) return;
      var hay = item.search || ((item.backend + " " + item.model).toLowerCase());
      if (query && hay.indexOf(query) === -1) return;
      if (!byBackend[item.backend]) { byBackend[item.backend] = []; order.push(item.backend); }
      byBackend[item.backend].push(item);
    });

    list.innerHTML = "";

    if (!order.length) {
      var none = document.createElement("div");
      none.className = "mgroup";
      none.textContent = onlyKeyed && !query ? "no provider has a key yet" : "nothing matches";
      list.appendChild(none);
      return;
    }

    order.forEach(function (backend) {
      var label = document.createElement("div");
      label.className = "mgroup";
      label.textContent = backend;
      list.appendChild(label);
      byBackend[backend].slice(0, limit).forEach(function (item) {
        list.appendChild(modelRow(item, after));
      });
    });
  }

  function closePop() {
    if (pop) { pop.remove(); pop = null; }
    $("modelChip").setAttribute("aria-expanded", "false");
  }

  function openPop() {
    var chip = $("modelChip");

    pop = document.createElement("div");
    pop.className = "pop";

    var search = document.createElement("input");
    search.type = "search";
    search.placeholder = "Search cheap models";
    search.setAttribute("aria-label", "Search models");

    var list = document.createElement("div");
    list.className = "modellist";

    function paint() {
      paintModelList(list, search.value.trim().toLowerCase(), false, 60, closePop);
    }

    var foot = document.createElement("div");
    foot.className = "popfoot";
    var footNote = document.createElement("span");
    footNote.textContent = "writes the forge-3 overlay";
    var footLink = document.createElement("button");
    footLink.type = "button";
    footLink.className = "poplink";
    footLink.textContent = "all models & keys";
    footLink.addEventListener("click", function (event) {
      event.stopPropagation();
      closePop();
      openSettings();
    });
    foot.appendChild(footNote);
    foot.appendChild(footLink);

    search.addEventListener("input", paint);
    pop.appendChild(search);
    pop.appendChild(list);
    pop.appendChild(foot);
    document.body.appendChild(pop);

    // anchored to the chip, so collapsing the rail cannot strand it
    var rect = chip.getBoundingClientRect();
    var width = pop.offsetWidth;
    pop.style.left = Math.max(10, Math.min(rect.left, window.innerWidth - width - 10)) + "px";
    pop.style.top = (rect.bottom + 7) + "px";

    paint();
    bindScroller(list);
    search.focus();
    chip.setAttribute("aria-expanded", "true");
  }

  /* ───────────────────────── settings ───────────────────────── */

  var settingsOpen = false;
  var keyEditorFor = "";     // backend whose paste box is showing

  var KEY_SOURCE = {
    stored: ["set", "stored by FORGE 3.0"],
    external: ["external", "supplied outside FORGE 3.0"],
    env: ["env", "supplied by an environment variable"],
    local: ["local", "runs on this machine — no key needed"],
    missing: ["missing", "no key yet"]
  };

  function refreshProviders() {
    if (!bridge()) return Promise.resolve();
    return Promise.all([bridge().model_choices(), bridge().backend_catalog()]).then(
      function (results) {
        if (results[0]) models = results[0];
        if (results[1]) backends = results[1];
      },
      function () {}
    );
  }

  function showPane(id) {
    ["paneModels", "paneKeys"].forEach(function (name) {
      $(name).hidden = name !== id;
    });
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (tab) {
      var on = tab.getAttribute("data-pane") === id;
      tab.classList.toggle("on", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  function paintSettingsModels() {
    var label = state
      ? (state.draft_backend || "?") + " · " + (state.draft_model || "no model")
      : "—";
    $("setPinned").textContent = label;
    $("setPinned").title = label;

    paintModelList(
      $("setModelList"),
      $("setModelSearch").value.trim().toLowerCase(),
      $("setOnlyKeyed").checked,
      200,
      null
    );
  }

  function keyCard(item) {
    var card = document.createElement("div");
    card.className = "keycard" + (keyEditorFor === item.backend ? " open" : "");

    var top = document.createElement("div");
    top.className = "keytop";

    var name = document.createElement("span");
    name.className = "keyname";
    name.textContent = item.backend;
    top.appendChild(name);

    var meta = KEY_SOURCE[item.source] || KEY_SOURCE.missing;
    var badge = document.createElement("span");
    badge.className = "keystate " + (item.source === "stored" ? "set" : item.source);
    badge.textContent = meta[0];
    badge.title = meta[1];
    top.appendChild(badge);

    var tag = document.createElement("span");
    tag.className = "keystate";
    tag.textContent = item.tag;
    top.appendChild(tag);

    var actions = document.createElement("div");
    actions.className = "keyact";

    if (!item.local) {
      var edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = item.source === "missing" ? "Add key" : "Replace";
      edit.addEventListener("click", function () {
        keyEditorFor = keyEditorFor === item.backend ? "" : item.backend;
        paintSettingsKeys();
      });
      actions.appendChild(edit);

      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "danger";
      remove.textContent = "Remove";
      // delete_key only unlinks the FORGE 3.0 keys folder; anything else would
      // report success and still answer on the next send
      remove.disabled = !item.removable;
      if (!item.removable) {
        remove.title = item.source === "env"
          ? "set by " + (item.detail || "an environment variable") + " — clear it there"
          : item.source === "external"
            ? "stored outside the FORGE 3.0 keys folder — remove that file by hand"
            : "nothing stored to remove";
      }
      remove.addEventListener("click", function () {
        if (remove.disabled) return;
        if (!window.confirm(
          "Remove the stored " + item.backend + " key?\n\n" +
          "This removes it from FORGE 3.0."
        )) return;
        bridge().delete_key(item.backend).then(function (result) {
          if (!result || !result.ok) {
            toast((result && result.error) || "could not remove the key");
            return;
          }
          keyEditorFor = "";
          applyState(result.state);
          refreshProviders().then(function () {
            paintSettings();
            toast(item.backend + " key removed");
          });
        });
      });
      actions.appendChild(remove);
    }

    top.appendChild(actions);
    card.appendChild(top);

    if (item.blurb) {
      var blurb = document.createElement("p");
      blurb.className = "keyblurb";
      blurb.textContent = item.blurb;
      card.appendChild(blurb);
    }

    if (item.detail) {
      var where = document.createElement("p");
      where.className = "keywhere";
      where.textContent = item.source === "env" ? "env · " + item.detail : item.detail;
      card.appendChild(where);
    }

    if (keyEditorFor === item.backend && !item.local) {
      var editor = document.createElement("div");
      editor.className = "keyedit";

      var input = document.createElement("input");
      input.type = "password";
      input.placeholder = "Paste the " + item.backend + " key";
      input.autocomplete = "off";
      input.spellcheck = false;

      var save = document.createElement("button");
      save.type = "button";
      save.textContent = "Save";

      var commit = function () {
        var value = input.value.trim();
        if (!value) { toast("key is empty"); return; }
        bridge().save_key(item.backend, value).then(function (result) {
          input.value = "";
          if (!result || !result.ok) {
            toast((result && result.error) || "could not save the key");
            return;
          }
          keyEditorFor = "";
          applyState(result.state);
          refreshProviders().then(function () {
            paintSettings();
            toast(item.backend + " key saved");
          });
        });
      };

      save.addEventListener("click", commit);
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") { event.preventDefault(); commit(); }
        // swallowed so Escape closes the paste box and not the whole sheet
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          keyEditorFor = "";
          paintSettingsKeys();
        }
      });

      editor.appendChild(input);
      editor.appendChild(save);
      card.appendChild(editor);
      setTimeout(function () { input.focus(); }, 0);
    }

    return card;
  }

  function paintSettingsKeys() {
    var list = $("setKeyList");
    list.innerHTML = "";

    if (!backends.length) {
      var none = document.createElement("p");
      none.className = "note";
      none.textContent = "no providers reported";
      list.appendChild(none);
      return;
    }

    backends.forEach(function (item) { list.appendChild(keyCard(item)); });

    var folder = backends[0] && backends[0].keys_dir;
    $("keysNote").textContent = folder
      ? "Stored only for FORGE 3.0 in " + folder
      : "Stored only for FORGE 3.0.";
  }

  function paintSettings() {
    if (!settingsOpen) return;
    paintSettingsModels();
    paintSettingsKeys();
  }

  function openSettings() {
    closePop();
    closeMenu();
    settingsOpen = true;
    keyEditorFor = "";
    $("settings").hidden = false;
    paintSettings();
    refreshProviders().then(function () {
      paintSettings();
      $("setModelSearch").focus();
    });
  }

  function closeSettings() {
    settingsOpen = false;
    keyEditorFor = "";
    $("settings").hidden = true;
  }

  /* ───────────────────────── composer ───────────────────────── */

  function grow() {
    var box = $("input");
    box.style.height = "auto";
    box.style.height = Math.min(box.scrollHeight, 170) + "px";
  }

  function send() {
    var box = $("input");
    var text = box.value.trim();
    if (!text || !bridge() || busy()) return;

    addUserTurn(text);
    pending = addBotTurn("", true);
    streamBuf = "";
    startedAt = Date.now();
    box.value = "";
    grow();
    setPhase("thinking");
    setAlert("");

    bridge().send(text).then(function (result) {
      if (!result || !result.ok) failPending((result && result.error) || "request rejected");
    }).catch(function (error) {
      failPending(String(error));
    });
  }

  /* ───────────────────────── events from the engine ───────────────────────── */

  window.forge3Event = function (event, payload) {
    payload = payload || {};
    if (payload.room && payload.room !== "forge") return;

    if (event === "phase") {
      setPhase(payload.phase || "thinking", payload);
      if (payload.phase === "thinking" && pending && !streamBuf) {
        setWaiting(pending.md, "thinking");
      }
      return;
    }

    if (event === "rewind") {
      if (pending) {
        streamBuf = "";
        setWaiting(pending.md, payload.fallback
          ? "falling back to another model"
          : "held — attempt " + (payload.attempt || "?") + " of " + (payload.maximum || "?"));
      }
      return;
    }

    if (event === "token") {
      if (!pending) return;
      streamBuf += payload.text || "";
      paintPending();
      return;
    }

    if (event === "complete") {
      var text = payload.text == null ? streamBuf : payload.text;
      if (!String(text).trim() && payload.notice) {
        if (pending) {
          pending.md.className = "md waiting";
          pending.md.textContent = payload.notice;
          pending = null;
          streamBuf = "";
        }
      } else {
        finishPending(text, payload.usage, payload.held, payload.hold_class, null);
      }
      setPhase("idle");
      setAlert("");
      refreshSessions();
      return;
    }

    if (event === "error") {
      failPending(payload.message || "request failed");
      return;
    }

    if (event === "cancelled") {
      if (pending && streamBuf) finishPending(streamBuf, null, false, null, "stopped");
      else if (pending) failPending("stopped");
      setPhase("idle");
      setAlert("");
      return;
    }

    if (event === "state") {
      applyState(payload.state);
      return;
    }

    if (event === "session") {
      if (payload.action === "new") resetThread([]);
      if (payload.action === "loaded" && payload.payload) resetThread(sessionTurns(payload.payload));
      refreshSessions(payload.id);
      return;
    }
  };

  /* ───────────────────────── wiring ───────────────────────── */

  $("composer").addEventListener("submit", function (event) {
    event.preventDefault();
    if (busy()) {
      if (bridge()) bridge().stop();
      return;
    }
    send();
  });

  $("sendBtn").addEventListener("click", function (event) {
    if (!busy()) return;
    event.preventDefault();
    if (bridge()) bridge().stop();
  });

  $("input").addEventListener("input", function () {
    grow();
    paintSendButton();
  });

  $("input").addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
      return;
    }
    if (event.key === "ArrowUp" && !$("input").value && lastUserText && !busy()) {
      event.preventDefault();
      $("input").value = lastUserText;
      grow();
      paintSendButton();
    }
  });

  $("newChat").addEventListener("click", function () {
    if (!bridge()) return;
    bridge().new_session().then(function (result) {
      if (!result || !result.ok) toast((result && result.error) || "could not start a chat");
      else $("input").focus();
    });
  });

  $("chatSearch").addEventListener("input", paintSessions);

  $("railBtn").addEventListener("click", function () {
    $("app").classList.toggle("railoff");
    closePop();
    closeMenu();
  });

  $("modelChip").addEventListener("click", function (event) {
    event.stopPropagation();
    if (pop) closePop();
    else openPop();
  });

  $("settingsBtn").addEventListener("click", function () {
    if (settingsOpen) closeSettings();
    else openSettings();
  });

  $("setClose").addEventListener("click", closeSettings);

  // clicking the scrim closes; clicking the sheet itself must not
  $("settings").addEventListener("click", function (event) {
    if (event.target === $("settings")) closeSettings();
  });

  Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (tab) {
    tab.addEventListener("click", function () { showPane(tab.getAttribute("data-pane")); });
  });

  $("setModelSearch").addEventListener("input", paintSettingsModels);
  $("setOnlyKeyed").addEventListener("change", paintSettingsModels);

  $("thread").addEventListener("scroll", function () {
    atBottom = nearBottom();
    $("jumpBtn").hidden = atBottom;
  });

  $("jumpBtn").addEventListener("click", function () { toBottom(true); });

  $("unlockBtn").addEventListener("click", unlock);
  $("pass").addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); unlock(); }
  });

  function unlock() {
    if (!bridge()) return;
    bridge().unlock($("pass").value).then(function (result) {
      $("unlockErr").textContent = (result && result.ok) ? "" : ((result && result.error) || "wrong passphrase");
      if (!result || !result.ok) return;
      $("pass").value = "";
      applyState(result.state);
      return bridge().bootstrap().then(function (data) {
        models = data.models || [];
        backends = data.backends || [];
        sessions = data.sessions || [];
        applyState(data.state);
        paintDrawer(data.drawer);
        resetThread((data.room && data.room.turns) || []);
        paintSessions();
        paintTitle();
        $("input").focus();
      });
    });
  }

  $("winMin").addEventListener("click", function () { if (bridge()) bridge().minimize(); });
  $("winMax").addEventListener("click", function () { if (bridge()) bridge().toggle_maximize(); });
  $("winClose").addEventListener("click", function () {
    if (!bridge()) return;
    if (busy() && !window.confirm("Forge is still drafting. Close anyway?")) return;
    bridge().close();
  });

  document.addEventListener("click", function (event) {
    if (pop && !pop.contains(event.target) && event.target !== $("modelChip")) closePop();
    if (openMenu && !openMenu.contains(event.target)) closeMenu();
  });

  document.addEventListener("keydown", function (event) {
    // innermost thing first: a popover over the sheet closes before the sheet
    if (event.key === "Escape") {
      if (pop) { closePop(); return; }
      if (openMenu) { closeMenu(); return; }
      if (settingsOpen) { closeSettings(); return; }
    }
    if ((event.ctrlKey || event.metaKey) && event.key === ",") {
      event.preventDefault();
      if (settingsOpen) closeSettings();
      else openSettings();
    }
    if ((event.ctrlKey || event.metaKey) && (event.key === "n" || event.key === "N")) {
      event.preventDefault();
      $("newChat").click();
    }
    if ((event.ctrlKey || event.metaKey) && (event.key === "f" || event.key === "F")) {
      event.preventDefault();
      $("app").classList.remove("railoff");
      $("chatSearch").focus();
      $("chatSearch").select();
    }
    if (event.key === "PageDown") {
      if (scrollThreadBy($("thread").clientHeight * 0.9)) event.preventDefault();
    }
    if (event.key === "PageUp") {
      if (scrollThreadBy(-$("thread").clientHeight * 0.9)) event.preventDefault();
    }
    if (event.ctrlKey && event.key === "Home") {
      $("thread").scrollTop = 0;
      atBottom = false;
      $("jumpBtn").hidden = nearBottom();
      event.preventDefault();
    }
    if (event.ctrlKey && event.key === "End") {
      toBottom(true);
      event.preventDefault();
    }
  });

  // rendered links copy instead of navigating — there is no back button in this window
  $("thread").addEventListener("click", function (event) {
    var link = event.target.closest ? event.target.closest("a[data-url]") : null;
    if (!link) return;
    event.preventDefault();
    var url = link.getAttribute("data-url").replace(/&amp;/g, "&");
    if (navigator.clipboard) navigator.clipboard.writeText(url).catch(function () {});
    toast("link copied");
  });

  window.addEventListener("resize", function () { closePop(); closeMenu(); });

  /* ───────────────────────── boot ───────────────────────── */

  function boot() {
    if (!bridge()) {
      setTimeout(boot, 80);
      return;
    }
    bridge().bootstrap().then(function (data) {
      models = data.models || [];
      backends = data.backends || [];
      sessions = data.sessions || [];
      applyState(data.state);
      paintDrawer(data.drawer);
      resetThread((data.room && data.room.turns) || []);
      paintSessions();
      paintTitle();
      paintSendButton();
      if (!(data.state && (data.state.state || data.state).locked)) $("input").focus();
    });
  }

  bindScroller($("thread"));
  bindScroller($("chats"));
  bindScroller($("sheetbody"));

  window.addEventListener("pywebviewready", boot);
  boot();
})();
