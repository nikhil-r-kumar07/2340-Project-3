// Developer knowledge-base interactions. All mutations still use normal
// server-rendered forms, so this script only improves clarity and feedback.

const sourceTabs = document.querySelectorAll("[data-source-tab]");
sourceTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    sourceTabs.forEach((candidate) => {
      const selected = candidate === tab;
      candidate.classList.toggle("is-active", selected);
      candidate.setAttribute("aria-selected", String(selected));
      document.getElementById(candidate.dataset.sourceTab).hidden = !selected;
    });
  });
});

const filterButtons = document.querySelectorAll("[data-source-filter]");
const sourceCards = document.querySelectorAll("[data-source-status]");
const emptyFilterMessage = document.getElementById("empty-filter-message");

filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const selectedFilter = button.dataset.sourceFilter;
    let visibleCount = 0;

    filterButtons.forEach((candidate) => {
      const selected = candidate === button;
      candidate.classList.toggle("is-active", selected);
      candidate.setAttribute("aria-pressed", String(selected));
    });

    sourceCards.forEach((card) => {
      const visible = selectedFilter === "all" || card.dataset.sourceStatus === selectedFilter;
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });

    if (emptyFilterMessage) emptyFilterMessage.hidden = visibleCount !== 0;
  });
});

document.querySelectorAll(".remove-source-form").forEach((form) => {
  form.addEventListener("submit", (event) => {
    const title = form.dataset.sourceTitle || "this source";
    if (!window.confirm(`Remove “${title}” from the catalog and search index?`)) {
      event.preventDefault();
    }
  });
});

document.querySelectorAll(".source-manager form").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (event.defaultPrevented) return;
    const button = form.querySelector("[data-busy-label]");
    if (!button) return;
    button.disabled = true;
    button.textContent = button.dataset.busyLabel;
    form.setAttribute("aria-busy", "true");
  });
});
