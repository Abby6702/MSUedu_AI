// Stops double-clicks on forms that take a while (generating or submitting a quiz).
document.addEventListener("DOMContentLoaded", () => {
  const subjectSelect = document.getElementById("subject_id");
  const topicSelect = document.getElementById("topic_id");

  if (subjectSelect && topicSelect) {
    const placeholder = topicSelect.options[0].cloneNode(true);
    const topics = Array.from(topicSelect.options).slice(1).map((option) => option.cloneNode(true));

    const filterTopics = () => {
      const subjectId = subjectSelect.value;
      const selectedTopic = topicSelect.value;
      const matchingTopics = topics.filter((option) => option.dataset.subjectId === subjectId);

      topicSelect.replaceChildren(placeholder.cloneNode(true), ...matchingTopics);
      topicSelect.disabled = !subjectId;
      topicSelect.value = matchingTopics.some((option) => option.value === selectedTopic)
        ? selectedTopic
        : "";
    };

    subjectSelect.addEventListener("change", filterTopics);
    filterTopics();
  }

  document.querySelectorAll("form[data-busy]").forEach((form) => {
    const button = form.querySelector("button[type=submit]");
    const original = button ? button.textContent : "";

    form.addEventListener("submit", () => {
      if (button) {
        button.disabled = true;
        button.textContent = form.dataset.busy;
      }
      const note = form.querySelector(".busy-note");
      if (note) note.hidden = false;
    });

    // If the student presses the browser's Back button, make the form usable again.
    window.addEventListener("pageshow", (event) => {
      if (event.persisted && button) {
        button.disabled = false;
        button.textContent = original;
      }
    });
  });
});