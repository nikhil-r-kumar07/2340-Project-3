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
function addMessage(role, text) {
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
  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
  return wrapper;
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
    addMessage("bot", result.answer);
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

messages.scrollTop = messages.scrollHeight;
