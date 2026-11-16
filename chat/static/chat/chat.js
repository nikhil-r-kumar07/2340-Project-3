// Chat page behavior (Story 1): send questions without reloading the page.

const form = document.getElementById("ask-form");
const input = document.getElementById("question");
const sendButton = document.getElementById("send");
const messages = document.getElementById("messages");
const examples = document.getElementById("examples");
const newChatButton = document.getElementById("new-chat");

// Django requires this token on POST requests to block cross-site attacks.
const csrfToken = form.querySelector("[name=csrfmiddlewaretoken]").value;

// Add a chat bubble. We use textContent (not innerHTML) so model output
// can never inject HTML or scripts into the page.
function addMessage(role, text, sources = []) {
  const wrapper = document.createElement("div");
  wrapper.className = role === "user" ? "message message-user" : "message message-bot";
  if (role === "error") wrapper.classList.add("message-error");

  const label = document.createElement("p");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Medicare Helper";

  const body = document.createElement("div");
  body.className = "message-text";
  body.textContent = text;

  wrapper.append(label, body);
  // add sources list under answers that have them
  if (sources.length) {
    wrapper.appendChild(buildSources(sources));
  }
  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
  return wrapper;
}

function buildSources(sources) {
  const box = document.createElement("div");
  box.className = "sources";

  const heading = document.createElement("p");
  heading.className = "sources-title";
  heading.textContent = "Where this answer came from:";
  const list = document.createElement("ol");
  list.className = "sources-list";
  for (const source of sources) {
    const item = document.createElement("li");
    item.value = source.number;
    const link = document.createElement("a");
    //only allow real http/https links so nothing like javascript: gets in
    link.href = /^https?:\/\//.test(source.url) ? source.url : "#";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = source.page ? `${source.title}, page ${source.page}` : source.title;
    item.appendChild(link);
    list.appendChild(item);
  }
  box.append(heading, list);
  return box;
}

async function postJSON(url, data) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Something went wrong.");
  return result;
}

async function askQuestion(question) {
  question = question.trim();
  if (!question) return;

  examples.hidden = true;
  addMessage("user", question);
  input.value = "";
  sendButton.disabled = true;

  const thinking = addMessage("bot", "Thinking");
  thinking.querySelector(".message-text").classList.add("typing");

  try {
    const result = await postJSON("/api/ask/", { question });
    thinking.remove();
    const answer = addMessage("bot", result.answer, result.sources || []);
    addReadAloudButton(answer);
  } catch (error) {
    thinking.remove();
    addMessage("error", error.message || "Sorry, something went wrong. Please try again.");
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  askQuestion(input.value);
});

// Enter sends; Shift+Enter makes a new line.
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!sendButton.disabled) askQuestion(input.value);
  }
});

// Clicking an example question asks it right away.
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => askQuestion(chip.textContent));
});

// "New chat" clears the saved conversation and reloads the page.
newChatButton.addEventListener("click", async () => {
  try {
    await postJSON("/api/reset/", {});
  } finally {
    window.location.reload();
  }
});

// ---------- Display settings (Story 8) ----------
// The change shows right away by swapping classes on <html>; style.css does the rest.
// It is also saved to the server so it stays after a reload.
const page = document.documentElement;
const sizeButtons = document.querySelectorAll(".size-option");
const contrastButton = document.getElementById("contrast-toggle");

function saveDisplay(setting) {
  // Saving is a nice-to-have: if it fails, the page still looks right until reload.
  postJSON("/api/display/", setting).catch(() => {});
}

sizeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const size = button.dataset.size;
    sizeButtons.forEach((b) => {
      page.classList.remove(`text-${b.dataset.size}`);
      b.setAttribute("aria-pressed", String(b === button));
    });
    page.classList.add(`text-${size}`);
    saveDisplay({ text_size: size });
  });
});

contrastButton.addEventListener("click", () => {
  const turnOn = contrastButton.getAttribute("aria-pressed") !== "true";
  page.classList.toggle("high-contrast", turnOn);
  contrastButton.setAttribute("aria-pressed", String(turnOn));
  saveDisplay({ high_contrast: turnOn });
});

// ---------- Read aloud (Story 9) ----------
// Uses the voice built into the browser (the Web Speech API), so there is
// nothing to install and no cost. Browsers without it never show the button.
const canSpeak = "speechSynthesis" in window;
const READING_RATE = 0.9;  // a little slower than normal, easier to follow
let readingButton = null;  // the button whose answer is being read right now
let readingId = 0;         // changes every time reading starts or stops

// The greeting's button (always on the page) is copied for each new answer.
const readAloudTemplate = document.querySelector(".read-aloud");

if (canSpeak) {
  document.querySelectorAll(".read-aloud").forEach((button) => { button.hidden = false; });
}

function addReadAloudButton(message) {
  const button = readAloudTemplate.cloneNode(true);
  button.hidden = !canSpeak;
  setReading(button, false);
  // Put it right under the answer text, above the sources list.
  message.querySelector(".message-text").after(button);
}

function setReading(button, isReading) {
  button.classList.toggle("is-reading", isReading);
  button.querySelector(".read-aloud-text").textContent = isReading ? "Stop reading" : "Read aloud";
}

function stopReading() {
  readingId += 1;
  if (readingButton) setReading(readingButton, false);
  readingButton = null;
  speechSynthesis.cancel();
}

function readAloud(button) {
  // Clicking the same button again stops it. Clicking another one switches answers.
  const wasReading = button === readingButton;
  stopReading();
  if (wasReading) return;

  // Skip citation numbers like [1] so the voice doesn't say "bracket one bracket".
  const text = button.closest(".message").querySelector(".message-text").textContent
    .replace(/\[\d+\]/g, "");

  // Some browsers (Chrome) stop after about 15 seconds of speech,
  // so the answer is read one sentence at a time.
  const sentences = text.split(/(?<=[.!?])\s+|\n+/).map((s) => s.trim()).filter(Boolean);
  if (!sentences.length) return;

  const id = readingId;
  readingButton = button;
  setReading(button, true);

  sentences.forEach((sentence, i) => {
    const utterance = new SpeechSynthesisUtterance(sentence);
    utterance.lang = "en-US";
    utterance.rate = READING_RATE;
    if (i === sentences.length - 1) {
      // Only reset the button if nothing else has started reading since.
      utterance.onend = () => { if (id === readingId) stopReading(); };
    }
    speechSynthesis.speak(utterance);
  });
}

// One listener for every Read aloud button, including ones added later.
messages.addEventListener("click", (event) => {
  const button = event.target.closest(".read-aloud");
  if (button) readAloud(button);
});

// Stop talking when the visitor leaves or reloads the page (for example, "New chat").
window.addEventListener("pagehide", () => { if (canSpeak) speechSynthesis.cancel(); });

messages.scrollTop = messages.scrollHeight;
