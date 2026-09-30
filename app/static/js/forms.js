// Client-side helper: warns immediately if the two passwords differ.
// The server ALSO checks this. Browser checks are only for convenience.
document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("form[data-check-match]");
  if (!form) return;

  const password = form.querySelector("#password");
  const confirm = form.querySelector("#confirm_password");

  function checkMatch() {
    confirm.setCustomValidity(
      confirm.value && confirm.value !== password.value ? "Passwords do not match." : ""
    );
  }
  password.addEventListener("input", checkMatch);
  confirm.addEventListener("input", checkMatch);
});