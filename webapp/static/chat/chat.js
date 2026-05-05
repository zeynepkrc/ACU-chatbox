/**
 * ACUknows — asenkron sohbet akışı
 */
(function () {
  "use strict";

  var API_URL = "/api/chat/";
  var FALLBACK_ERROR =
    "⚠️ Şu an asistan cevap veremiyor, lütfen daha sonra tekrar deneyiniz.";
  var WELCOME_TEXT =
    "Aşağıdan mesajınızı yazarak sohbete başlayın.";

  var messagesEl = document.getElementById("messages");
  var form = document.getElementById("chat-form");
  var input = document.getElementById("message-input");
  var sendBtn = document.getElementById("send-btn");
  var newChatBtn = document.getElementById("new-chat-btn");

  if (!messagesEl || !form || !input || !sendBtn) {
    return;
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function removeWelcome() {
    var w = messagesEl.querySelector(".messages__welcome");
    if (w) {
      w.remove();
    }
    messagesEl.classList.remove("messages--empty");
  }

  function appendWelcome() {
    var existing = messagesEl.querySelector(".messages__welcome");
    if (existing) {
      return;
    }
    messagesEl.classList.add("messages--empty");
    var div = document.createElement("div");
    div.className = "messages__welcome";
    div.setAttribute("role", "status");
    div.textContent = WELCOME_TEXT;
    messagesEl.appendChild(div);
    scrollToBottom();
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
      appendWelcome();
      input.value = "";
      autoResize();
      input.focus();
      scrollToBottom();
    });
  }

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

    removeWelcome();
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
