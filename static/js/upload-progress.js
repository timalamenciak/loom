(function () {
  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) {
      return "0 MB";
    }
    const units = ["bytes", "KB", "MB", "GB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return unit === 0 ? `${value} ${units[unit]}` : `${value.toFixed(1)} ${units[unit]}`;
  }

  function setProgress(root, percent, label) {
    const bar = root.querySelector("[data-upload-progress-bar]");
    const text = root.querySelector("[data-upload-progress-text]");
    const value = Math.max(0, Math.min(100, percent));
    if (bar) {
      bar.style.width = `${value}%`;
      bar.setAttribute("aria-valuenow", String(Math.round(value)));
    }
    if (text) {
      text.textContent = label;
    }
  }

  function disableForm(form, disabled) {
    form.querySelectorAll("button, input, select, textarea").forEach((el) => {
      el.disabled = disabled;
    });
  }

  function handleResponse(xhr) {
    if (xhr.status >= 200 && xhr.status < 400) {
      if (xhr.responseURL && xhr.responseURL !== window.location.href) {
        window.location.assign(xhr.responseURL);
        return;
      }
      document.open();
      document.write(xhr.responseText);
      document.close();
      return;
    }
    throw new Error(`Upload failed with HTTP ${xhr.status}`);
  }

  function initForm(form) {
    const root = form.querySelector("[data-upload-progress]");
    if (!root) {
      return;
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      root.hidden = false;
      disableForm(form, true);
      setProgress(root, 0, "Preparing upload...");

      const xhr = new XMLHttpRequest();
      xhr.open(form.method || "POST", form.action || window.location.href, true);
      xhr.upload.addEventListener("progress", (progressEvent) => {
        if (!progressEvent.lengthComputable) {
          setProgress(root, 8, "Uploading...");
          return;
        }
        const percent = (progressEvent.loaded / progressEvent.total) * 100;
        setProgress(
          root,
          percent,
          `Uploading ${formatBytes(progressEvent.loaded)} of ${formatBytes(progressEvent.total)}`
        );
      });
      xhr.addEventListener("load", () => {
        try {
          handleResponse(xhr);
        } catch (error) {
          setProgress(root, 100, error.message);
          disableForm(form, false);
        }
      });
      xhr.addEventListener("error", () => {
        setProgress(root, 100, "Upload failed before the server responded.");
        disableForm(form, false);
      });
      xhr.addEventListener("abort", () => {
        setProgress(root, 100, "Upload canceled.");
        disableForm(form, false);
      });
      xhr.upload.addEventListener("load", () => {
        setProgress(root, 100, "Upload complete. Processing on the server...");
      });
      xhr.send(formData);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form[data-upload-progress-form]").forEach(initForm);
  });
})();
