/**
 * ACU.knows — asenkron sohbet akışı
 */
(function () {
  "use strict";

  var API_URL = "/api/chat/";
  var FALLBACK_ERROR =
    "⚠️ Şu an asistan cevap veremiyor, lütfen daha sonra tekrar deneyiniz.";

  var messagesEl = document.getElementById("messages");
  var form = document.getElementById("chat-form");
  var input = document.getElementById("message-input");
  var sendBtn = document.getElementById("send-btn");
  var newChatBtn = document.getElementById("new-chat-btn");
  var welcomePanel = document.getElementById("welcome-panel");

  if (!messagesEl || !form || !input || !sendBtn) {
    return;
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setWelcomePanelVisible(visible) {
    if (!welcomePanel) {
      return;
    }
    welcomePanel.classList.toggle("welcome-panel--hidden", !visible);
  }

  function setMessagesEmptyState(empty) {
    if (empty) {
      messagesEl.classList.add("messages--empty");
    } else {
      messagesEl.classList.remove("messages--empty");
    }
  }

  function renderSidebarHistory() {
    var dataEl = document.getElementById("chat-history-data");
    var listEl = document.getElementById("chat-history-list");
    var emptyHint = document.getElementById("sidebar-empty-hint");
    if (!listEl) {
      return;
    }
    var items = [];
    try {
      if (dataEl && dataEl.textContent) {
        items = JSON.parse(dataEl.textContent);
      }
    } catch (e) {
      items = [];
    }
    listEl.innerHTML = "";
    if (!items.length) {
      if (emptyHint) {
        emptyHint.hidden = false;
      }
      return;
    }
    if (emptyHint) {
      emptyHint.hidden = true;
    }
    items.forEach(function (item) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sidebar__item";
      btn.textContent = item.title || item.name || "Sohbet";
      if (item.id != null) {
        btn.dataset.chatId = String(item.id);
      }
      btn.setAttribute("aria-label", "Geçmiş: " + (item.title || "Sohbet"));
      li.appendChild(btn);
      listEl.appendChild(li);
    });
  }

  function appendBubble(role, text, extraClass) {
    var article = document.createElement("article");
    article.className =
      "message message--" + role + (extraClass ? " " + extraClass : "");
    var meta = document.createElement("div");
    meta.className = "message__meta";
    meta.textContent = role === "user" ? "Siz" : "Asistan";
    var body = document.createElement("p");
    body.className = "message__body";
    body.textContent = text;
    article.appendChild(meta);
    article.appendChild(body);
    messagesEl.appendChild(article);
    scrollToBottom();
    return article;
  }

  function appendTypingBubble() {
    var article = document.createElement("article");
    article.className =
      "message message--assistant message--loading message--typing";
    article.setAttribute("aria-busy", "true");
    article.setAttribute("aria-live", "polite");

    var meta = document.createElement("div");
    meta.className = "message__meta";
    meta.textContent = "Asistan";

    var body = document.createElement("div");
    body.className = "message__body message__body--typing";

    var label = document.createElement("span");
    label.className = "typing-label";
    label.textContent = "AI yanıt veriyor";

    var dots = document.createElement("span");
    dots.className = "typing-dots";
    dots.setAttribute("aria-hidden", "true");
    for (var i = 0; i < 3; i++) {
      var d = document.createElement("span");
      dots.appendChild(d);
    }

    body.appendChild(label);
    body.appendChild(dots);
    article.appendChild(meta);
    article.appendChild(body);
    messagesEl.appendChild(article);
    scrollToBottom();
    return article;
  }

  function setLoading(loading) {
    sendBtn.disabled = loading;
    input.disabled = loading;
  }

  function autoResize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 128) + "px";
  }

  function parseJsonSafe(res) {
    return res.text().then(function (text) {
      if (!text || !text.trim()) {
        return null;
      }
      try {
        return JSON.parse(text);
      } catch (e) {
        return null;
      }
    });
  }

  renderSidebarHistory();

  if (newChatBtn) {
    newChatBtn.addEventListener("click", function () {
      messagesEl.innerHTML = "";
      setMessagesEmptyState(true);
      setWelcomePanelVisible(true);
      input.value = "";
      autoResize();
      input.focus();
      scrollToBottom();
    });
  }

  document.querySelectorAll(".quick-action").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var q = btn.getAttribute("data-question");
      if (!q) {
        return;
      }
      input.value = q;
      autoResize();
      input.focus();
      form.requestSubmit();
    });
  });

  input.addEventListener("input", autoResize);

  input.addEventListener("keydown", function (e) {
    if (e.isComposing) {
      return;
    }
    var isEnter = e.key === "Enter" || e.key === "NumpadEnter";
    if (!isEnter) {
      return;
    }
    if (e.shiftKey) {
      return;
    }
    e.preventDefault();
    form.requestSubmit();
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = (input.value || "").trim();
    if (!text) {
      return;
    }

    setWelcomePanelVisible(false);
    setMessagesEmptyState(false);
    appendBubble("user", text);
    input.value = "";
    autoResize();

    var typingEl = appendTypingBubble();
    setLoading(true);

    var longWaitTimer = window.setTimeout(function () {
      var label = typingEl && typingEl.querySelector(".typing-label");
      if (label) {
        label.textContent =
          "Model yanıt hazırlıyor (bu birkaç dakika sürebilir)…";
      }
    }, 45000);

    fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: text }),
    })
      .then(function (res) {
        return parseJsonSafe(res).then(function (data) {
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (result) {
        typingEl.remove();
        if (
          result.ok &&
          result.data &&
          result.data.ok === true &&
          result.data.answer
        ) {
          appendBubble("assistant", String(result.data.answer));
        } else {
          appendBubble("assistant", FALLBACK_ERROR, "message--error");
        }
      })
      .catch(function () {
        typingEl.remove();
        appendBubble("assistant", FALLBACK_ERROR, "message--error");
      })
      .finally(function () {
        window.clearTimeout(longWaitTimer);
        setLoading(false);
        input.focus();
        scrollToBottom();
      });
  });

  window.addEventListener("load", scrollToBottom);
})();
