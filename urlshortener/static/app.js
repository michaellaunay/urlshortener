/* Copy-to-clipboard for the generated short link.
 *
 * Progressive: the link is selectable text and works with no script at
 * all; this only saves a gesture. The button is hidden when the
 * Clipboard API is unavailable rather than left there doing nothing.
 */
(function () {
  "use strict";

  var button = document.querySelector(".copy");
  if (!button) { return; }

  if (!navigator.clipboard || !navigator.clipboard.writeText) {
    button.hidden = true;
    return;
  }

  var idleLabel = button.textContent;
  var doneLabel = button.getAttribute("data-copied-label") || idleLabel;
  var timer = null;

  button.addEventListener("click", function () {
    navigator.clipboard.writeText(button.getAttribute("data-copy")).then(function () {
      button.textContent = doneLabel;
      button.setAttribute("data-state", "done");
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        button.textContent = idleLabel;
        button.removeAttribute("data-state");
      }, 2500);
    });
  });
})();
