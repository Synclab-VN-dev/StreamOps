/* #86: in-page confirmation matching pinned MagicPath, never a native alert.
 * Only explicit confirmation permits the caller to submit a lifecycle command.
 */
(() => {
  let active = false;
  function ask({title, message, confirmLabel="Confirm", notice=""}) {
    if (active) return Promise.resolve(false);
    active = true;
    return new Promise(resolve => {
      const origin = document.activeElement;
      const overlay = document.createElement("div");
      overlay.className = "gm-confirm-overlay";
      overlay.innerHTML = `<section class="gm-confirm-dialog" role="dialog" aria-modal="true"
          aria-labelledby="gm-confirm-title" aria-describedby="gm-confirm-message">
        <div class="gm-confirm-head">
          <h2 id="gm-confirm-title"></h2>
          <button class="gm-confirm-close" type="button" aria-label="Close confirmation">×</button>
        </div>
        <p id="gm-confirm-message"></p>
        <p class="gm-confirm-note" hidden></p>
        <div class="gm-confirm-actions">
          <button class="gm-confirm-cancel" type="button">Cancel</button>
          <button class="gm-confirm-accept" type="button"></button>
        </div>
      </section>`;
      overlay.querySelector("#gm-confirm-title").textContent = title;
      overlay.querySelector("#gm-confirm-message").textContent = message;
      overlay.querySelector(".gm-confirm-accept").textContent = confirmLabel;
      const note = overlay.querySelector(".gm-confirm-note");
      if (notice) {note.textContent = notice;note.hidden=false;}
      const cancel = overlay.querySelector(".gm-confirm-cancel");
      const accept = overlay.querySelector(".gm-confirm-accept");
      const close = overlay.querySelector(".gm-confirm-close");
      const focusable = [close,cancel,accept];
      function finish(approved) {
        document.removeEventListener("keydown", onKey, true);
        window.removeEventListener("pagehide", onHide);
        overlay.remove();
        active = false;
        if (origin?.isConnected && typeof origin.focus === "function") origin.focus({preventScroll:true});
        resolve(approved);
      }
      function onHide(){finish(false);}
      function onKey(event) {
        if (event.key === "Escape") {
          event.preventDefault();event.stopImmediatePropagation();finish(false);
        } else if (event.key === "Tab") {
          const i=focusable.indexOf(document.activeElement);
          if(event.shiftKey && (i===0 || i===-1)) {event.preventDefault();accept.focus();}
          else if(!event.shiftKey && i===focusable.length-1) {event.preventDefault();close.focus();}
        }
      }
      cancel.addEventListener("click",()=>finish(false));
      close.addEventListener("click",()=>finish(false));
      accept.addEventListener("click",()=>finish(true));
      document.addEventListener("keydown",onKey,true);
      window.addEventListener("pagehide",onHide,{once:true});
      document.body.append(overlay);
      cancel.focus();
    });
  }
  window.StreamOpsConfirmation = {ask};
})();
