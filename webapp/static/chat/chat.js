/**
 * ACU AI Asistanı — asenkron sohbet akışı (ADIM 2)
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

  if (!messagesEl || !form || !input || !sendBtn) {
    return;
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
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
    article.className = "message message--assistant message--loading message--typing";
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

  input.addEventListener("input", autoResize);

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = (input.value || "").trim();
    if (!text) {
      return;
    }

    appendBubble("user", text);
    input.value = "";
    autoResize();

    var typingEl = appendTypingBubble();
    setLoading(true);

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
        setLoading(false);
        input.focus();
        scrollToBottom();
      });
  });

  window.addEventListener("load", scrollToBottom);
})();
